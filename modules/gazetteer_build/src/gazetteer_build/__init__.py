# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Build the gazetteer SQLite file from local place, station and DSO area files (ADR-0007).

Each input is a GeoJSON FeatureCollection with a top-level `snapshot_date` member:

- places: properties `name`, `place` (place type), `osm` (e.g. "node/123")
- stations: properties `name`, `alt_name`, `old_name`, `short_name` (";"-separated as in
  OSM), `operator`, `voltage`, `osm`
- DSO areas: properties `dso_mastr_nr`, `grid_level`

Features without a name are skipped. The output always replaces the previous file.
"""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from shapely import STRtree
from shapely.geometry import shape

ALT_NAME_KEYS = ["alt_name", "old_name", "short_name"]

SCHEMA = """
CREATE TABLE source (name TEXT PRIMARY KEY, snapshot_date TEXT NOT NULL);
CREATE TABLE dso_area (
    dso_mastr_nr TEXT NOT NULL, grid_level TEXT NOT NULL, PRIMARY KEY (dso_mastr_nr, grid_level)
);
CREATE TABLE place (id INTEGER PRIMARY KEY, name TEXT NOT NULL, place_type TEXT, osm TEXT);
CREATE TABLE station (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, alt_names TEXT NOT NULL, operator TEXT,
    voltage TEXT, osm TEXT
);
CREATE TABLE entry_area (
    kind TEXT NOT NULL CHECK (kind IN ('place', 'station')),
    entry_id INTEGER NOT NULL,
    dso_mastr_nr TEXT NOT NULL,
    grid_level TEXT NOT NULL,
    FOREIGN KEY (dso_mastr_nr, grid_level) REFERENCES dso_area (dso_mastr_nr, grid_level)
);
CREATE INDEX entry_area_dso ON entry_area (dso_mastr_nr, grid_level, kind);
"""


def gazetteer_path() -> Path:
    """Return the gazetteer file inside NAP_DATA_DIR.

    Returns:
        Path of `gazetteer/gazetteer.sqlite`.

    Raises:
        SystemExit: If NAP_DATA_DIR is unset or not a directory.
    """
    value = os.environ.get("NAP_DATA_DIR")
    if not value or not Path(value).expanduser().is_dir():
        raise SystemExit("error: NAP_DATA_DIR must point to the nap_data directory")
    return Path(value).expanduser() / "gazetteer" / "gazetteer.sqlite"


def read_features(path: Path) -> tuple[str, list[dict]]:
    """Read a GeoJSON FeatureCollection.

    Args:
        path: Input file.

    Returns:
        The snapshot date and the features.

    Raises:
        SystemExit: If the file has no `snapshot_date`.
    """
    collection = json.loads(path.read_text(encoding="utf-8"))
    if not collection.get("snapshot_date"):
        raise SystemExit(f"error: {path} has no top-level snapshot_date")
    return collection["snapshot_date"], collection["features"]


def named(features: list[dict]) -> list[dict]:
    """Drop features without a name; their position + 1 becomes the entry id.

    Args:
        features: GeoJSON features.

    Returns:
        The features that have a name.
    """
    return [feature for feature in features if feature["properties"].get("name")]


def alt_names(properties: dict) -> list[str]:
    """Return a station's alternative names.

    Args:
        properties: OSM-style station properties.

    Returns:
        The `alt_name`, `old_name` and `short_name` values, split at ";".
    """
    return [
        name.strip()
        for key in ALT_NAME_KEYS
        for name in (properties.get(key) or "").split(";")
        if name.strip()
    ]


def build(places: Path, stations: Path, dso_areas: Path, target: Path) -> None:
    """Write the gazetteer, replacing any previous file.

    Every place and station is assigned to each DSO area its geometry intersects.

    Args:
        places: Places GeoJSON.
        stations: Stations GeoJSON.
        dso_areas: DSO areas GeoJSON, one feature per DSO and grid level.
        target: Gazetteer file to write.
    """
    inputs = {"places": places, "stations": stations, "dso_areas": dso_areas}
    snapshot_dates = {}
    features = {}
    for name, path in inputs.items():
        snapshot_dates[name], features[name] = read_features(path)
    areas = features["dso_areas"]
    area_tree = STRtree([shape(area["geometry"]) for area in areas])

    places_named = named(features["places"])
    stations_named = named(features["stations"])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.partial")
    partial.unlink(missing_ok=True)
    with closing(sqlite3.connect(partial)) as connection, connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO source VALUES (?, ?)", snapshot_dates.items())
        connection.executemany(
            "INSERT OR IGNORE INTO dso_area VALUES (?, ?)",
            [
                (area["properties"]["dso_mastr_nr"], area["properties"]["grid_level"])
                for area in areas
            ],
        )
        connection.executemany(
            "INSERT INTO place VALUES (?, ?, ?, ?)",
            [
                (entry_id, place["name"], place.get("place"), place.get("osm"))
                for entry_id, place in enumerate(
                    (feature["properties"] for feature in places_named), start=1
                )
            ],
        )
        connection.executemany(
            "INSERT INTO station VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    entry_id,
                    station["name"],
                    json.dumps(alt_names(station)),
                    station.get("operator"),
                    station.get("voltage"),
                    station.get("osm"),
                )
                for entry_id, station in enumerate(
                    (feature["properties"] for feature in stations_named), start=1
                )
            ],
        )
        for kind, entries in [("place", places_named), ("station", stations_named)]:
            if not entries:
                continue
            entry_index, area_index = area_tree.query(
                [shape(entry["geometry"]) for entry in entries], predicate="intersects"
            )
            connection.executemany(
                "INSERT INTO entry_area VALUES (?, ?, ?, ?)",
                [
                    (
                        kind,
                        int(entry) + 1,
                        areas[area]["properties"]["dso_mastr_nr"],
                        areas[area]["properties"]["grid_level"],
                    )
                    for entry, area in zip(entry_index, area_index)
                ],
            )
    partial.replace(target)


def main(argv: list[str] | None = None) -> None:
    """Run `gazetteer-build`.

    Args:
        argv: Command-line arguments; defaults to `sys.argv`.
    """
    parser = argparse.ArgumentParser(
        prog="gazetteer-build", description="Build $NAP_DATA_DIR/gazetteer/gazetteer.sqlite."
    )
    parser.add_argument("--places", type=Path, required=True)
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--dso-areas", type=Path, required=True)
    args = parser.parse_args(argv)
    target = gazetteer_path()
    build(args.places, args.stations, args.dso_areas, target)
    print(f"Wrote {target}")
