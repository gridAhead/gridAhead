<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Switch classification output with a pointer file, not a symlink

A classification run writes a complete, immutable generation to `classified/set_<set>/.versions/scheme_<scheme>_<uuid>/` and then makes it current. Readers must see all files of one generation, never a manifest from one run and a table from another. Until DB_VERSION 20 a `scheme_<scheme>` symlink did the switch. On Windows that fails: creating a symlink needs Developer Mode or admin rights, `os.replace` cannot replace a directory, and git checkouts with `core.symlinks=false` turn the link into a text file. Since DB_VERSION 21, the text file `classified/set_<set>/scheme_<scheme>.current` holds the name of the current generation (`scheme_<scheme>_<uuid>`) and is replaced atomically with `os.replace`, which works on every platform without extra rights.

## Consequences

- Readers read the pointer once and then use only that generation directory, which keeps the guarantee the symlink gave. The generation name is checked against `scheme_<scheme>_<32 hex>`, so a pointer cannot lead outside `.versions/`.
- The current output is no longer browsable at `classified/set_<set>/scheme_<scheme>/`; open the pointer to find the generation.
- Windows may refuse to replace a pointer that another process holds open; `data.replace_file` retries briefly, since readers hold it only while reading a few bytes.
- The path layout changed, so DB_VERSION went from 20 to 21 (ADR-0003). `nap-tool upgrade` converts each `scheme_<scheme>` link, whether a symlink or a text file from a git checkout, into a pointer and then sets the new version; it is safe to rerun after a failure.
- The mechanism lives in `nap_tool/generations.py` and is also used by the `geocoded/` stage (ADR-0007).
