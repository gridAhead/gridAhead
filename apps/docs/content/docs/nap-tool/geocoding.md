---
title: Geocoding
description: How nap-tool turns the locations of classified measures into coordinates with offline place data and optional OSM objects.
mode: wide
sidebar:
  label: Geocoding
  order: 3
---

<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

`uv run nap-tool place-data fetch [--force]` downloads BKG GN250 into
`$NAP_DATA_DIR/place_data/gn250/<sha8>/` and points `place_data/gn250.current` at it.
The folder must be gitignored in nap_data (the command warns if it is not); also ignore
`/geocoded/` there like `/classified/`, because geocoding generations are never pruned and
each holds a full copy of the classified table. Each version holds the unchanged download
(`source.zip`), the prepared lookup (`places.csv`: municipalities `AX_Gemeinde` and
settlements `AX_Ortslage` with WGS84 points) and `manifest.json` (URL, SHA-256, data
status, object classes, attribution). `geocode` checks `places.csv` and the manifest on
load; `fetch` additionally repairs a missing or modified `source.zip`. `fetch` keeps the
current version only if the download is the same, all its files verify and it was built for
the configured `object_classes`; otherwise (or with `--force`) it rebuilds the lookup, also
over a malformed pointer. The command prints
`updated`, `unchanged` or `repaired` (the current version was damaged and has been rebuilt). It fails if the download
is not a ZIP archive ("GN250 download is not a valid ZIP archive") or a GN250 row is
malformed (the message names the line and NNID). Files are written atomically.

`uv run nap-tool geocode --scheme-id <id> [--set-id <id>]` reads the current
classification output of the set and writes a new generation
`$NAP_DATA_DIR/geocoded/set_<set>/.versions/scheme_<scheme>_<uuid>/`, made current by
`geocoded/set_<set>/scheme_<scheme>.current` (ADR-0006, ADR-0007):

- `geocoded.csv`: every column of `classified.csv` plus the columns below.
- `geocoded.geojson`: one point per resolved location (opens in QGIS).
- `geocode_report.md` / `.json`: one overall resolved share; counts per status; total and
  resolved per kind and per DSO; DSO anchors; locations far from their DSO; with OSM data,
  how many locations got an OSM object and how many of those were rescued; sources and
  attribution.
- `unresolved_names.csv`: unresolved names with reason, count and DSOs.
- `run_manifest.json`: fingerprint and SHA-256 of every file.

Rules and limits live in `config/geocode.yaml`.

## Refusals and staleness

`geocode` refuses:

- a missing or stale classification output. Freshness is checked against the default
  `config/classify*.yaml`, so after `classify --config-path …` rerun `classify` with the
  default configuration first;
- missing place data, or place data whose files do not match their manifest hashes;
- place data built for other `object_classes` than `geocode.yaml` lists (run
  `place-data fetch`, which rebuilds for the configured classes);
- OSM data whose files do not match their manifest hashes, or that was fetched for other
  `osm.classes` than `geocode.yaml` lists (run `place-data osm-fetch`). Without OSM
  data `geocode` runs on GN250 alone.

An unknown scheme or set is refused before anything is written. The other checks run under
the per-scheme lock, so a refused run can leave an empty `geocoded/set_<set>/` folder; the
published output stays as it was.

Geocoded output is stale when the classification run, `classified.csv`, the place data (ZIP
and `places.csv` hashes), the OSM data (export and `objects.csv` hashes; also when OSM data
is added or removed) or `geocode.yaml` changed.

## Columns

For `<x>` in `start`, `end` (only records with `inferred_record_type = measure`):

| Column | Content |
| --- | --- |
| `inferred_location_<x>_lat`, `_lon` | WGS84, six decimals |
| `inferred_location_<x>_match` | GN250 name and municipality key, e.g. `Waren (Müritz) (13071156)`; just the name if GN250 has no key |
| `inferred_location_<x>_geocode` | how the point was found, see below |
| `inferred_location_<x>_precision` | `object` (position of an OSM object) or `settlement` (GN250 centre); empty if unresolved |

Statuses: `exact`, `comma_part`, `strip_suffix`, `strip_qualifier`, `nearest_to_anchor`;
a suffix `+station` means a station name was placed at its settlement. With OSM data:
`osm_substation`, `osm_plant` (the point is that OSM object; `_match` is its OSM name, with
no municipality key).
`unresolved:no_match`, `unresolved:ambiguous_no_anchor`, `unresolved:ambiguous_far`;
`skipped:code`, `skipped:street_address` (a street address without at least two non-empty
comma parts).

`resolved_share` in the report is resolved locations divided by all start and end locations
of measures; skipped locations count in the denominator.

## Matching

Names are normalized the same way on both sides (casefold, `ß`→`ss`, `St.`→`Sankt`,
punctuation to spaces). Places in the place data are also found under their long name (`NAME2`) and
without their qualifier (`Waren (Müritz)` → `Waren`). A qualifier is a trailing `(…)`,
`/…`, dotted `a.d.`, `a.`, `b.`, `i.`, or one of the words `bei`, `am`, `an der`, `an den`,
`im`, `in`, `in der`, `auf`, `ob der`, `vor der` followed by a name. The words must stand
alone: "Groß Ammensleben" is not cut.

The first step that finds a candidate wins: the whole name; each comma part; without a
trailing direction word (`suffix_words`); without a trailing qualifier. A street address is
only geocoded via its comma parts. Candidates in the same municipality count once; places
without a municipality key stay distinct. Several candidates: the one nearest to the DSO
anchor — the median of the DSO's names that matched exactly one place in step `exact` —
within `max_anchor_km`. A DSO needs `min_anchor_points` such places for an anchor.

Precision is the settlement unless OSM data finds the object (next section): then a station
is placed at its reported OSM point. Either way it is not a surveyed position.

## OSM objects (optional)

`uv run nap-tool place-data osm-fetch [--from-file PATH] [--force]` stores the named OSM
substations and power plants of Germany in `$NAP_DATA_DIR/place_data/osm_objects/<sha8>/`
and points `place_data/osm_objects.current` at it. A version holds the unchanged export
(`source.json`), the prepared lookup (`objects.csv`: id, class, name, operator, ref,
voltage, WGS84 point; ways and relations use their centre) and `manifest.json` (URL,
SHA-256, data status = OSM base timestamp, classes, counts, attribution). The folder lives
beside the GN250 data and is gitignored with it. Like `fetch`, it keeps the current version
only for the same export, intact files and the configured `osm.classes`. The command prints
`updated`, `unchanged` or `repaired`, the object count and how many unnamed objects were skipped. It fails if the
export is not Overpass JSON ("OSM download is not valid JSON"), carries an Overpass
`remark` (possibly truncated), or holds no named objects.

The public Overpass server is busy at times and not meant for automated use, so only this
command queries it (busy answers are retried with a pause of 30 s, then 60 s) and `geocode`
never does. If the server stays busy, run the query returned by `overpass_query` in
`nap_tool/geocoder/osm_data.py` in Overpass Turbo, export the raw JSON and import it with
`--from-file`.

After the settlement lookup, `geocode` asks the OSM objects for a better position:

- The location kind selects the allowed OSM classes (`osm.kinds`); other kinds, and names
  that are only station words, never match. A kind in `rescue_only_kinds` (`place`,
  `search_area`) uses OSM only when the settlement lookup found nothing.
- Names are compared like place names, without the station words in `osm.strip_words`
  (`Umspannwerk Waren` matches `Waren`), and also without a trailing qualifier.
- A class mismatch is refused: a power plant is never placed for a substation name.
- The reference point is the settlement found, else the DSO anchor. Without either, nothing
  matches: a name that is unique in Germany says nothing about where the DSO's object is. The nearest
  object wins (lowest id on a tie): within `osm.max_km` of the settlement, or within
  `matching.max_anchor_km` of the DSO anchor (a rescue; the anchor stands for the whole
  DSO area).
- If an object's `operator` shares a word with the DSO name (ignoring `operator_stop_words`),
  only such objects are considered, even if they are too far: a same-named object of another
  operator is more likely a different place.

The report counts matches under `osm` (`matched` objects, of which `rescued` had no
settlement result) and lists the OSM source; the Markdown report shows them in one line.
Classes, kinds, words and `max_km` live in `config/geocode.yaml`. The hash of the OSM data
is part of the freshness check.

## Attribution

Results that show GN250 positions must credit "© BKG (<year of last download>) dl-de/by-2-0,
Datenquellen: https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_gn250.pdf"
and, because the data is modified, a change notice ("Daten verändert: Auswahl der Gemeinden
und Ortslagen, Koordinaten von UTM32 nach WGS84 umgerechnet"). On web pages, link BKG to
https://www.bkg.bund.de and the licence to https://www.govdata.de/dl-de/by-2-0. The
manifest and the report contain the exact text.

Results that use OSM objects must credit "© OpenStreetMap contributors"
(https://www.openstreetmap.org/copyright). The data is under the ODbL 1.0; a database
derived from it must stay open under the same licence (ADR-0008). The manifest and the
report contain the attribution text.
