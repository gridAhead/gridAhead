<!--
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# DB migration — discussion and spec

Captures the `/grill-me` session that turned the `README.md` ERD into a
concrete target schema, plus the migration this implies. This is a spec, not
an implementation — no code has been written yet.

## Background

Current state: `data/` (gitignored) is the source of truth. Three parallel
directory trees hold JSON sidecar metadata beside PDF/CSV files:

- `data/raw/<slug>/` — `metadata.json` + `nap.pdf`, overwritten on every
  `download` (no version history today).
- `data/processed/extracted/<slug>/<tool>/` — `metadata.json` + per-table
  CSVs, one directory per extractor.
- `data/processed/compared/<slug>/` — `metadata.json` + accepted CSVs.

Goal: replace this with a single SQLite database as the source of truth for
the whole pipeline (`download` / `extract` / `compare`), matching the ERD in
`README.md`.

## Discussion — locked decisions

**Stack**
- SQLite. Raw `sqlite3` stdlib, no ORM, no new dependency.
- The DB replaces `data/` entirely; it is not a cache or export of it.

**History semantics**
- `run` = one invocation of `download`. `document` keeps full history: every
  download inserts a new row, nothing is overwritten. This is a behavior
  change from today's "always overwrite `nap.pdf`" rule.
- `table_extracted` and `table_compared` stay **overwrite-in-place**
  (upsert), matching today's on-disk behavior — re-running `extract` or
  `compare` replaces the prior row rather than accumulating history.
- Failed extraction attempts (`ExtractionMetadata.error` set, zero tables)
  are **not** persisted. Only successful `table_extracted` rows exist in the
  DB; failures stay operational (console/log output), not schema.

**Field-level corrections against the original ERD draft**
- `document.publication_date` → renamed to `current_from` + `current_to`.
  Traced to `downloader/sources.py` (`currentFrom`/`currentTo` from
  VNBdigital's GraphQL schema): this is a validity window used to pick the
  newest candidate, not a true publication date. No real publication-date
  field exists in the source data.
- `document` gains `sha256` — dropped from the original ERD but tracked
  today (`files[].sha256`) and used by the ReIndex importer to match
  results to source PDFs.
- `table_extracted.document_pages` (single int) → replaced by
  `pages_json` + `regions_json` (JSON text columns), because a table can
  span multiple source pages and carries per-page bounding boxes
  (`ExtractedTable.regions`). Stored as JSON rather than a child table:
  this is provenance data, not something queried by page number today: per
  the stdlib/no-ORM direction, don't build relational structure for a query
  pattern that doesn't exist yet.
- `table_extracted` gains `table_number` (extractor-internal ordering,
  needed to reconstruct original filenames), `status` (extractor's own
  validation status), `imported_from` and `source_markdown` (ReIndex import
  provenance — real audit data, kept).
- `table_extracted` does **not** get its own `merged` flag. The source data
  has two different "merged" concepts (`ExtractedTable.merged`: multiple
  regions merged into one CSV within an extractor run vs.
  `table_compared.merged`: multiple extractor outputs merged in the
  comparator) — the extractor-level one is dropped rather than added under
  a colliding or renamed column.
- `table_harmonized` stays FK-only, unimplemented — confirmed as future
  work, not a gap in this migration.

## Target schema

```sql
CREATE TABLE vnb (
    provider_id   INTEGER PRIMARY KEY,
    provider_name TEXT NOT NULL,
    provider_slug TEXT NOT NULL UNIQUE
);

CREATE TABLE run (
    run_id       INTEGER PRIMARY KEY,
    run_datetime TEXT NOT NULL  -- ISO 8601 UTC
);

CREATE TABLE document (
    document_id   INTEGER PRIMARY KEY,
    vnb_id        INTEGER NOT NULL REFERENCES vnb(provider_id),
    run_id        INTEGER NOT NULL REFERENCES run(run_id),
    file          BLOB NOT NULL,
    sha256        TEXT NOT NULL,
    current_from  TEXT,          -- ISO 8601, nullable (VNBdigital may omit)
    current_to    TEXT,          -- ISO 8601, nullable
    source        TEXT NOT NULL, -- hub | custom | manual | vnbdigital
    source_url    TEXT,
    document_name TEXT NOT NULL
);

CREATE TABLE extractor (
    extractor_id INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE
);

CREATE TABLE table_extracted (
    table_extracted_id INTEGER PRIMARY KEY,
    document_id         INTEGER NOT NULL REFERENCES document(document_id),
    extractor_id         INTEGER NOT NULL REFERENCES extractor(extractor_id),
    data                 BLOB NOT NULL,
    table_number         INTEGER NOT NULL,
    pages_json           TEXT NOT NULL,   -- JSON list[int]
    regions_json          TEXT NOT NULL,   -- JSON list[{page, bbox}]
    rows                 INTEGER NOT NULL,
    columns               INTEGER NOT NULL,
    title                 TEXT,
    source_id             TEXT,
    status                 TEXT NOT NULL,
    imported_from         TEXT,
    source_markdown       TEXT,
    UNIQUE (document_id, extractor_id, table_number)  -- upsert key
);

CREATE TABLE table_compared (
    table_compared_id INTEGER PRIMARY KEY,
    data               BLOB NOT NULL,
    merged             INTEGER NOT NULL,  -- bool
    manually_edited     INTEGER NOT NULL,  -- bool
    ready               INTEGER NOT NULL   -- bool
    -- upsert key TBD: needs (vnb_id, output filename) or equivalent,
    -- since table_compared has no direct FK to vnb/document today.
);

CREATE TABLE comparison (
    table_extracted_id INTEGER NOT NULL REFERENCES table_extracted(table_extracted_id),
    table_compared_id   INTEGER NOT NULL REFERENCES table_compared(table_compared_id),
    PRIMARY KEY (table_extracted_id, table_compared_id)
);

CREATE TABLE table_harmonized (
    table_harmonized_id INTEGER PRIMARY KEY,
    table_compared_id     INTEGER NOT NULL REFERENCES table_compared(table_compared_id)
    -- remaining fields undefined, future work
);
```

Open point not yet resolved: `table_compared` has no FK back to `vnb` or
`document` in the ERD, only reachable via `comparison` → `table_extracted` →
`document` → `vnb`. Its upsert key (needed since `table_compared` stays
overwrite-in-place) has to be derived through that join — equivalent to
today's `(provider_slug, output filename)` pairing in
`processed/compared/<slug>/metadata.json`.

## Migration plan

One-off backfill from the current `data/` tree into a new SQLite file,
followed by rewriting `download`/`extract`/`compare` to read/write the DB
directly instead of the filesystem. Order matters — later steps depend on
IDs assigned by earlier ones:

1. **Schema.** Create the SQLite file and run the DDL above.
2. **`vnb`.** One row per distinct `provider_slug` seen across
   `data/raw/*/metadata.json` (`provider` → `provider_name`,
   `provider_slug` as-is).
3. **`run`.** Since there's no existing run concept, synthesize one `run`
   row per distinct `downloaded_at` timestamp found in `data/raw/*/metadata.json`
   — today's data has one download per provider with its own timestamp, so
   this becomes effectively one run per provider for the backfill; going
   forward, `download` creates a real `run` row per invocation.
4. **`document`.** One row per `data/raw/<slug>/metadata.json`, reading
   `nap.pdf` bytes as the `file` blob. Map `provider_slug` → `vnb_id`,
   synthesized run → `run_id`, `files[0].sha256` → `sha256`,
   `current_from`/`current_to` from the metadata if present (today's
   `metadata.json` only stores `current_from`; `current_to` will be null
   for backfilled rows), `source_type` → `source`, `document_id`/`document_name`
   copied through, `source_url` copied through.
5. **`extractor`.** Seed rows for `docling`, `llamaparse`, `reindex` (the
   three known tool directory names).
6. **`table_extracted`.** For each
   `data/processed/extracted/<slug>/<tool>/metadata.json`, for each entry in
   `tables`: resolve `document_id` via `provider_slug` + `source_sha256`
   (matches the ReIndex importer's existing matching strategy), resolve
   `extractor_id` via `tool`, read the sibling CSV file as the `data` blob,
   map `table_number`, `pages` → `pages_json`, `regions` → `regions_json`,
   `rows`, `columns`, `title`, `source_id`, `status`,
   `imported_from`/`source_markdown` from the top-level metadata fields.
   Entries with `error` set and no `tables` are skipped (not persisted, per
   the locked decision).
7. **`table_compared`.** For each
   `data/processed/compared/<slug>/metadata.json`, for each entry in
   `tables`: read the sibling CSV as `data`, copy `merged`,
   `manually_edited`, `ready`.
8. **`comparison`.** For each `table_compared` row, resolve each
   `source_files` entry (`"<tool>/nap_table_<n>.csv"`) back to its
   `table_extracted_id` via `(document_id, extractor_id, table_number)` and
   insert one `comparison` row per source file.
9. **Verification.** Row counts per table cross-checked against file counts
   on disk (number of `metadata.json` files, number of `tables` entries
   summed) before treating the backfill as complete.
10. **Cutover.** Only after backfill is verified: rewrite
    `download`/`extract`/`comparator` commands to read/write the DB instead
    of `data/`. `data/` itself is left in place but no longer written to
    (not deleted as part of this migration — a separate, explicit decision).

Not covered by this spec (explicitly out of scope, confirmed during
discussion): rewriting the CLI commands themselves, `table_harmonized`'s
remaining fields, and any UI/CLI changes needed to expose document history
now that `download` no longer overwrites.
