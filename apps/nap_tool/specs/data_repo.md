<!--
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Spec: file-based data repo

## Problem

PDFs and all tables live as BLOBs in `nap_tool.sqlite` (333 MB). Data is opaque, not diffable, and not traceable outside the tool. Several extractors (LLMPDF, docling, non-AI tools) must coexist, and as much as possible should stay deterministic and reviewable.

## Solution

Files are the payload, the DB holds metadata. PDFs and every table stage are stored as files in a standalone git repo; the DB stores each file's relative path plus SHA-256. The data repo is independent of `nap_tool` and internal (access on request), so data never reaches GitHub.

```
$NAP_DATA_DIR/
├── README.md                     # layout + workflow conventions
├── .gitattributes                # *.sqlite *.pdf binary, *.csv text eol=lf
├── nap_tool.sqlite               # metadata, relative paths, sha256, flags — no BLOBs
├── pdf/<vnb_slug>/<year>_<sha8>.pdf
├── extracted/<vnb_slug>/<year>_<sha8>/<extractor>/table_01.csv
├── reviewed/<vnb_slug>/<year>_<sha8>/<extractor>/table_01.csv
└── harmonized/<scheme_slug>.csv
```

## Rules

### Location

- Path comes from env var `NAP_DATA_DIR` (shell or `.env` in the `nap_tool` root). Unset → abort with a clear error; no fallback to `./data`.
- Path must exist. Not a git repo → warning only (allows tests on tmp dirs).

### Layout

- **Stage first**, then document. Stages: `pdf`, `extracted`, `reviewed`, `harmonized`.
- **Document key** = `<nap_year>_<sha256[:8]>`, under `<vnb_slug>/`. Derived from content, never from DB ids, so paths survive a DB rebuild.
- **PDF**: single file `pdf/<vnb_slug>/<key>.pdf`. Original name stays in `document.document_name`.
- **Extracted**: `extracted/<vnb_slug>/<key>/<extractor>/table_NN.csv`, zero-padded. Extractors write CSVs only; pages, regions, markdown and other tool output stay in the DB.
- **Reviewed**: mirrors the extracted path (relation extracted ↔ reviewed is 1:1). The file is written only when a table is **approved**; drafts and history stay in the DB, `ignored` writes no file. File exists ⇔ approved.
- **Harmonized**: one file per scheme, `harmonized/<scheme_slug>.csv`, containing all tables of all VNBs. Leading provenance columns: `vnb_slug,document_key,extractor,table_number,row_number`. Renaming a scheme renames the file (`git mv`).

### Runs and re-extraction

- Runs exist only in the DB (`run_document`, m:n) and never appear in paths.
- Same PDF in a later run → same SHA → same key → files already exist → link only, no re-extraction.
- `--force` overwrites `extracted/…/<extractor>/`; history is in git. A changed tool setup that should be compared side by side gets a new extractor name.

### CSV format

- UTF-8 without BOM, `,` delimiter, RFC 4180 quoting, LF line endings.
- `extracted` and `reviewed`: values are unchanged strings (`"1.234,5"` stays as is).
- `harmonized`: normalized values, `.` as decimal separator.
- DB paths are relative to `$NAP_DATA_DIR`, `/` as separator.

### Hash check and manual edits

- Every load of a PDF or CSV compares the file's SHA-256 with the DB.
- Mismatch → show "manually edited". Action "accept" stores the new hash and sets `manually_edited = 1` permanently.
- Every derived file stores `source_sha256` (hash of its input) in the DB. Input changed → downstream is stale:
  - **reviewed**: flag "source changed"; never overwritten automatically. User accepts the new source hash or redoes the review.
  - **harmonized**: build artifact. UI shows "harmonized outdated"; regenerate via button or CLI (no background job). Manual edits in harmonized are warned about, since the next regeneration overwrites them; corrections belong in `reviewed`.

### Git workflow

- No LFS, no auto-commit. People commit and push manually.
- Convention: one person writes at a time, `git pull` before working (the SQLite file cannot be merged).
- `README.md` documents layout and convention.

### Migration

- One-time script: write existing BLOBs (PDFs, extracted tables, approved reviews, harmonized outputs) into the layout above, replace them with path + SHA-256, drop the BLOB columns.

## Out of scope

Git LFS, auto-commit, concurrent writers, configurable layout, versioned review drafts in files, storing raw extractor output as files.
