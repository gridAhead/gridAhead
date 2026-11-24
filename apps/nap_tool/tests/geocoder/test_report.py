# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Markdown geocoding report."""

from nap_tool.geocoder.report import markdown_report

REPORT = {
    "locations": 8,
    "resolved": 4,
    "resolved_share": 0.5,
    "by_status": {"exact": 3, "unresolved:no_match": 1},
    "by_kind": {"place": {"resolved": 3, "total": 4}},
    "by_dso": {
        "a": {"resolved": 4, "total": 7, "anchor": [51.06, 13.0], "anchor_points": 3},
        "b": {"total": 1, "unresolved": 1, "anchor": None, "anchor_points": 0},
    },
    "far_from_dso": [
        {
            "row_id": "2",
            "role": "start",
            "dso_slug": "a",
            "name": "Waren",
            "match": "Waren (Müritz) (13000001)",
            "distance_km": 272.1,
        }
    ],
    "place_data": {
        "source": "BKG GN250",
        "version": "abcd1234",
        "sha256": "ab" * 32,
        "data_status": "31.12.2024",
        "attribution": "© BKG (2026) dl-de/by-2-0",
    },
}


def test_markdown_report() -> None:
    text = markdown_report(REPORT)
    assert "Resolved: 4 of 8 locations (50.0%)" in text
    assert "| `exact` | 3 |" in text
    assert "| a | 7 | 4 | 51.0600, 13.0000 | 3 |" in text
    assert "| b | 1 | 0 | — | 0 |" in text
    assert "| 2 | start | a | Waren | Waren (Müritz) (13000001) | 272.1 |" in text
    assert "© BKG (2026) dl-de/by-2-0" in text
    assert "https://www.govdata.de/dl-de/by-2-0" in text
    assert (
        "https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_gn250.pdf" in text
    )


def test_pipes_in_names_are_escaped() -> None:
    far = [{**REPORT["far_from_dso"][0], "name": "A|B"}]
    text = markdown_report({**REPORT, "far_from_dso": far})
    assert "| A\\|B |" in text


def test_markdown_report_without_far_places() -> None:
    text = markdown_report({**REPORT, "far_from_dso": []})
    assert "## Far from DSO anchor (0)" in text
    assert "| Row |" not in text


def test_osm_lines_and_attribution() -> None:
    report = {
        **REPORT,
        "osm": {"matched": 3, "rescued": 2},
        "osm_objects": {
            "source": "OpenStreetMap via Overpass",
            "version": "abcd1234",
            "sha256": "cd" * 32,
            "data_status": "2026-11-24T08:00:00Z",
            "attribution": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
        },
    }
    text = markdown_report(report)
    assert "OSM objects: 3 matched (2 rescued)" in text
    assert "© OpenStreetMap contributors" in text and "2026-11-24T08:00:00Z" in text


def test_no_osm_lines_without_osm_data() -> None:
    text = markdown_report({**REPORT, "osm": {"matched": 0, "rescued": 0}, "osm_objects": None})
    assert "OpenStreetMap" not in text and "OSM objects" not in text
