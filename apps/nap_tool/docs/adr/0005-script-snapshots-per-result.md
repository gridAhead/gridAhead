<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Store a snapshot of the producing code with every result

Each extracted table and each cleaning records the code that produced it: extraction writes `scripts/extract/<tool>/<sha256>.json` (adapter source, tool version, pages) into `nap_data`, cleaning stores its script and hash in the same way. Recording only the `nap_tool` commit was rejected: the two repositories are versioned separately (ADR-0001), and a snapshot inside `nap_data` keeps every result reproducible without the tool repository's history.

## Consequences

- A cleaning is only regenerated when its source hash, configuration or script hash changes.
- The 2026 tables imported by external scripts keep their script snapshots under `nap_data/scripts/extract/` too.
