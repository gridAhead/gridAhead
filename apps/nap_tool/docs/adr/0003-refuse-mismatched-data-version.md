<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Refuse a data repository of another version, never upgrade automatically

`nap_tool` and `nap_data` are versioned separately, so a checkout of one can be older than the other. The format version (`DB_VERSION`) is stored as `PRAGMA user_version`; every open refuses a database of another version and says which repository to update. `connect()` creates the schema only in an empty file and never migrates: a silent upgrade would rewrite shared data that colleagues on an older `nap_tool` could then no longer read, and a downgrade is impossible.

## Consequences

- Any change an older or newer `nap_tool` would misread (SQL schema, seeded ids, path layout, parsed file formats) bumps `DB_VERSION`; `tests/test_db_version.py` fails whenever `SCHEMA` changes.
- An upgrade is an explicit step that sets the new `user_version` in the same transaction as its changes.
