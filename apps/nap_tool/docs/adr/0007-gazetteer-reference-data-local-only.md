<!--
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Gazetteer reference data stays local and is never committed

The gazetteer (place and station names per DSO area) is built from OpenStreetMap (ODbL) and MaStR data. Publishing these sources, or files derived from them, could put the project under their licence terms. That includes the CC-BY repository `gridAhead_data` and `nap_data`, which may become public later. A pipeline (`modules/gazetteer_build`) therefore downloads the sources and writes `$NAP_DATA_DIR/gazetteer/gazetteer.sqlite`, which is git-ignored. The file is always rebuildable, so it carries no format version and has no upgrade path. Shipping the reference data in `gridAhead_data`, as planned in the NAP classification handover of 2026-11-20, was rejected for these licence reasons.

## Consequences

- Every machine that classifies must run the build itself. A fresh checkout of `nap_data` has no gazetteer.
- The gazetteer helps Claude propose location names, and a proposal may adopt an OSM spelling. Such values reach `classified.csv` only through the proposal path (ADR-0002) and carry a flag, so the ODbL question for the published dataset stays visible and has to be settled before publication.
