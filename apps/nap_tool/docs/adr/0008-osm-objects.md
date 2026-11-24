<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# OSM objects refine geocoding and are fetched by hand

GN250 places a substation at the centre of the settlement it is named after. Locations that name a substation or power plant get the position of the matching OpenStreetMap object instead, with GN250 as fallback. The objects come from the public Overpass server, which is busy at times and not meant for automated use, so `nap-tool place-data osm-fetch` is a manual command (with retries and an import from a saved export via `--from-file`) and `geocode` never queries Overpass. The export is stored as a hash-named version in `$NAP_DATA_DIR/place_data/osm_objects/` beside the GN250 data, through the shared `versioned_data` module, with the same integrity checks. The data is optional: without it `geocode` behaves as before; with it, the hashes join the freshness check and the report. Matching rules (kinds, classes, station words, operator hint, distance limit) live in `config/geocode.yaml`; kinds `place` and `search_area` use OSM only to rescue what GN250 could not resolve.

OSM data is licensed under the ODbL 1.0. Using it requires the attribution "© OpenStreetMap contributors"; a database derived from it must stay open under the same licence. That fits this project, but it is a deliberate choice, and people who publish `geocoded.csv` need to carry the attribution (the report and manifest contain it). Precision is the position OSM reports for the object (the centre of a way or relation), not a surveyed one; `inferred_location_<x>_precision` tells `object` from `settlement`.
