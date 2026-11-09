<!--
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Instructions

Goal: download grid extension plans, extract their tables with multiple tools,
and review accepted CSV output with complete provenance.

## What's already built

- CLI commands for download, extraction, and comparison.
- Provider registry and VNBdigital downloader.
- Per-tool extraction layout under `data/processed/extracted/<slug>/<tool>/`.
- Docling, LlamaParse Agentic, and published llmPDF extractor adapters.
- llmPDF Review output under `data/processed/compared/<slug>/` with approval
  and manual-edit provenance.

See `README.md` for the full folder layout and "Add a provider / source
type / extraction tool" recipes.

## Processing workflow

1. `download` writes stable `data/raw/<slug>/nap.pdf` files.
2. `extract --tool <name>` writes raw per-tool CSV files and metadata.
3. `compare` opens llmPDF Review and writes approved tables to
   `processed/compared` using the existing nap-tool CSV contract.

## Ground rules

- Always fetch the *latest* version of a document and overwrite — no
  version history to manage.
- LlamaParse costs money and must only run when explicitly selected.
- llmPDF is an external PyPI dependency; do not vendor or modify its source.
- Keep `download` and `extract` independent — `extract` reads whatever is
  in `data/raw/`, regardless of how it got there (including files you drop
  in by hand).
- New tool or module later? Add the file, wire one line into `cli.py`. No
  plugin system needed.
