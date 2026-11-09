<!--
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Spec: run ↔ document many-to-many

## Problem

Every `download` appends a new document row per fetched PDF, even when the bytes are unchanged. Extractions, comparisons and reviews hang off the document, so unchanged PDFs must be extracted and reviewed again after every run.

## Solution

A run links to documents instead of owning them. If a downloaded PDF's SHA-256 already exists for that provider, the run is only linked to the existing document, and all of that document's extracted tables, comparisons and reviews carry over.

```sql
CREATE TABLE run_document (
    run_id INTEGER NOT NULL REFERENCES run(run_id),
    document_id INTEGER NOT NULL REFERENCES document(document_id),
    PRIMARY KEY (run_id, document_id)
);
-- document: drop run_id; CHECK ((file IS NULL) = (sha256 IS NULL)); UNIQUE (vnb_id, sha256)
```

## Rules

- **Identity** = provider + SHA-256. Always download; deduplicate afterwards.
- **Metadata** on a match: newest non-NULL values overwrite the existing document's.
- **Run membership**: a run links only documents it fetched and verified. Nothing is carried forward.
- **Current document** of a provider: the one linked to the highest run id (tie-break: highest document id). One shared query replaces all "newest by `run_id`" lookups.
- **Pending discovery rows** (no file) have no links. If filling one yields existing bytes, merge it into the existing document: link it, copy metadata, re-key the aux source identity, delete the pending row.
- **Comparison clearing** when a provider's current SHA-256 changes: unchanged.
- **`extract`** skips (document, tool) pairs that already have tables; `--force` re-extracts.
- **Migration**: explicit `nap-tool db migrate`. It backfills links from `document.run_id` and rebuilds `document` in one transaction, aborting on duplicate (provider, SHA-256). Other commands fail fast on the old schema.
- **UI**: card shows "Last seen in run #N · date (K runs)", sorted by latest run; schema diagram and i18n updated.

## Out of scope

Skipping downloads before fetching, cross-provider deduplication, per-run metadata, run-filtered harmonization views.
