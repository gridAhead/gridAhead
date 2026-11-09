<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Classification output is files only

Classification writes `classified/set_<set>/scheme_<scheme>/` (classified table, validation report, unmapped values) and switches it atomically via a symlink; nothing goes into the database. Its rules in `config/classify*.yaml` change often during review, and the output is fully derived from one harmonized table plus that config, so it can always be regenerated. Keeping it out of the schema avoids a DB_VERSION bump (ADR-0003) for every new derived column.
