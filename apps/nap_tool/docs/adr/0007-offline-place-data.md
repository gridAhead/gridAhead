<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Geocoding uses offline place data kept out of git

Geocoding resolves place names from classified measures against BKG GN250 (dl-de/by-2-0), downloaded once per version into `$NAP_DATA_DIR/place_data/` and matched locally. An online geocoder (public Nominatim) is rate-limited to one request per second and its answers change over time; a self-hosted one needs a running service for every user. The local lookup is deterministic, fast, and reproducible: each geocode run records the SHA-256 of the place data it used. The place data folder is a re-downloadable build artifact of public data and must never be committed: it has to be gitignored in nap_data (`nap-tool place-data fetch` warns if it is not) and is rebuilt by `nap-tool place-data fetch`. `/geocoded/` should be ignored in nap_data as well, like `/classified/`, because geocoding generations are never pruned and each holds a full copy of the classified table. Like classification (ADR-0004), geocoding writes files only, in its own `geocoded/` stage with pointer-switched generations (ADR-0006), so a change of matching rules needs no DB_VERSION bump. The pointer and generation helpers live in `nap_tool/generations.py`, shared by classification and geocoding. GN250 holds municipalities and settlements at 1:250 000 but no streets; a second source is added only if the unresolved report shows the need.
