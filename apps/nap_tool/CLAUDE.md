<!--
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# CLAUDE.md

`nap-tool` turns the Netzausbaupläne of German DSOs into one reviewed, harmonized and
classified dataset. Vocabulary: `GLOSSARY.md`. Decisions and their reasons: `docs/adr/`.
Coding standards: `CODING_STANDARDS.md`.

## Setup

- Data lives in the separate repository `nap_data`; every command needs `NAP_DATA_DIR`
  (see `.env.example`). Committing and pushing `nap_data` is manual.
- `uv sync --group dev`; extraction tools are extras (`docling`, `llmpdf`, `llamaparse`).
- Check: `uv run ruff check . && uv run ruff format . && uv run pytest`.
- Geocoding needs the place data: `uv run nap-tool place-data fetch` downloads BKG GN250 into
  `$NAP_DATA_DIR/place_data/` (must be gitignored in nap_data, never committed; `place-data fetch`
  warns if it is not; also ignore `/geocoded/` like `/classified/`; ADR-0007).
- Optional OSM objects for more precise points: `uv run nap-tool place-data osm-fetch`
  (public Overpass, run by hand; ODbL, ADR-0008).
- Frontend (`src/nap_tool/ui/frontend/`): after changing `src/`, run
  `npm ci && npm run build && npm test` (Node ≥ 22) and commit the rebuilt bundle in
  `ui/static/`. If npm does not match Node:
  `pnpm import && pnpm install --frozen-lockfile && rm pnpm-lock.yaml`.

## Gotchas

- The nap-tool docs page (`../docs/content/docs/nap-tool/index.mdx`) describes the CLI,
  folder layout and data version; update it when commands, paths or `DB_VERSION` change.
- Bump `DB_VERSION` for anything a nap_tool of the other version would misread: SQL schema,
  seeded ids, path layout, parsed file formats (ADR-0003). Each bump needs a step in
  `database/upgrade.py`; `nap-tool upgrade` applies it to nap_data.
- Classification output is switched by a pointer file, not a symlink, so it works on
  Windows (ADR-0006).
- Classification rules live in `config/classify*.yaml`; the written reference is
  `../docs/content/docs/nap-tool/classification.md`. Patterns on case-folded text use `ss`
  for `ß`.
- Geocoding rules live in `config/geocode.yaml`; the written reference is
  `../docs/content/docs/nap-tool/geocoding.md`.
- Before working on NAP 2026 data, record keys, asset codes or validation, read
  `../docs/content/docs/nap-tool/nap-2026.md`.
- `extract` offers only docling and llmPDF; `comparator/` and `database_ui/` are stale.

## Guardrails

- Cell values change only through deterministic code; AI proposes mappings or rules for
  human review (ADR-0002).
- LlamaParse is paid: run it only when explicitly selected (`LLAMA_CLOUD_API_KEY`).
- Tests build their own data repository in `tmp_path`. Trial runs on real data call
  `classifier.classify()` with `service.inputs()`/`load_rows()` read-only and write
  elsewhere.
