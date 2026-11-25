# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Tiny gazetteer inputs: two overlapping DSO areas with different grid levels.

DSO 1 serves HV on the square (0, 0)-(10, 10) and MV on (0, 0)-(5, 5).
DSO 2 serves MV on (5, 0)-(15, 10), overlapping DSO 1's HV area.
"""

import json

import gazetteer_build
import pytest

DSO_1 = "SNB900000000001"
DSO_2 = "SNB900000000002"


def square(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def point(x: float, y: float) -> dict:
    return {"type": "Point", "coordinates": [x, y]}


def collection(features: list[tuple[dict, dict]], snapshot_date: str) -> dict:
    return {
        "type": "FeatureCollection",
        "snapshot_date": snapshot_date,
        "features": [
            {"type": "Feature", "geometry": geometry, "properties": properties}
            for geometry, properties in features
        ],
    }


PLACES = [
    (point(2, 2), {"name": "Albbruck", "place": "town", "osm": "node/1"}),
    (point(3, 3), {"name": "Großweiler", "place": "village", "osm": "node/2"}),
    (point(7, 2), {"name": "Dogern", "place": "village", "osm": "node/3"}),
    (point(12, 2), {"name": "Fernau", "place": "hamlet", "osm": "node/4"}),
    # Enough similar names inside DSO 1's MV area to exceed the default candidate count.
    *[
        (point(1, 1 + index * 0.5), {"name": f"Weiler {index}", "place": "hamlet"})
        for index in range(6)
    ],
]

STATIONS = [
    (
        point(2.5, 2.5),
        {
            "name": "Albbruck",
            "alt_name": "Albbruck Süd;Albbruck 1",
            "old_name": "Kiesenbach",
            "operator": "Netze Eins",
            "voltage": "110000;20000",
            "osm": "way/11",
        },
    ),
    (
        square(4, 8, 4.5, 8.5),
        {"name": "Umspannwerk Hochfeld", "operator": "Netze Eins", "voltage": "110000"},
    ),
]

DSO_AREAS = [
    (square(0, 0, 10, 10), {"dso_mastr_nr": DSO_1, "grid_level": "HV"}),
    (square(0, 0, 5, 5), {"dso_mastr_nr": DSO_1, "grid_level": "MV"}),
    (square(5, 0, 15, 10), {"dso_mastr_nr": DSO_2, "grid_level": "MV"}),
]


def write_inputs(directory, places=PLACES, stations=STATIONS, dso_areas=DSO_AREAS) -> list[str]:
    """Write the input files and return the matching gazetteer-build arguments."""
    arguments = []
    for option, features, date in [
        ("--places", places, "2026-11-01"),
        ("--stations", stations, "2026-11-02"),
        ("--dso-areas", dso_areas, "2026-10-01"),
    ]:
        path = directory / f"{option.removeprefix('--')}.geojson"
        path.write_text(json.dumps(collection(features, date)), encoding="utf-8")
        arguments += [option, str(path)]
    return arguments


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A temporary NAP_DATA_DIR."""
    root = tmp_path / "nap_data"
    root.mkdir()
    monkeypatch.setenv("NAP_DATA_DIR", str(root))
    return root


@pytest.fixture
def built(tmp_path, data_dir):
    """A NAP_DATA_DIR with a gazetteer built from the tiny inputs."""
    gazetteer_build.main(write_inputs(tmp_path))
    return data_dir
