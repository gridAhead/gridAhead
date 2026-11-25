<!--
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# AGENTS.md

gridAhead monorepo: apps in `apps/`, shared modules in `modules/`. Each app has its own instructions (e.g. `apps/nap_tool/CLAUDE.md`).

## Agent skills

### Issue tracker

Issues live in GitHub Issues of `gridAhead/gridAhead`, managed with `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context: `GLOSSARY-MAP.md` at the root points to each context's `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
