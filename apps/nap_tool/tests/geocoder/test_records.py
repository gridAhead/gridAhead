# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Row-level geocoding: statuses, columns, anchors, report data."""

from nap_tool.geocoder.match import Matcher, Place
from nap_tool.geocoder.records import GEOCODE_FIELDS, geocode_rows


def place(id: str, name: str, ags: str, lat: float, lon: float, population: int = 100) -> Place:
    return Place(id, name, "", "AX_Ortslage", ags, lat, lon, population)


MATCHER = Matcher(
    [
        place("1", "Musterdorf", "01000001", 51.0, 13.0),
        place("2", "Waren (Müritz)", "13000001", 53.5, 12.7),
        place("3", "Kirchberg", "14000001", 51.1, 13.1),
        place("4", "Kirchberg", "09000001", 48.0, 11.0),
        place("6", "Beispielstadt", "01000002", 51.06, 13.06, 5000),
    ],
    ["nord"],
)


def record(
    row_id: str,
    start: str,
    start_kind: str,
    end: str = "",
    end_kind: str = "",
    record_type: str = "measure",
    dso: str = "a",
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "dso_slug": dso,
        "inferred_record_type": record_type,
        "inferred_location_start": start,
        "inferred_location_start_kind": start_kind,
        "inferred_location_end": end,
        "inferred_location_end_kind": end_kind,
    }


ROWS = [
    record("1", "Musterdorf", "substation"),
    record("2", "Waren", "place", "Beispielstadt", "place"),
    record("3", "Kirchberg", "place"),
    record("4", "Nirgendwo", "place"),
    record("5", "UW12", "code"),
    record("6", "Hauptstraße 5", "street_address"),
    record("7", "Musterdorf", "place", record_type="collective"),
    record("8", "Kirchberg", "place", dso="b"),
]


def test_statuses_and_columns() -> None:
    result = geocode_rows(ROWS, MATCHER, 100, 3)
    rows = {row["row_id"]: row for row in result.rows}
    start = "inferred_location_start"
    assert rows["1"][f"{start}_geocode"] == "exact+station"
    assert rows["1"][f"{start}_match"] == "Musterdorf (01000001)"
    assert (rows["1"][f"{start}_lat"], rows["1"][f"{start}_lon"]) == ("51.000000", "13.000000")
    assert rows["2"][f"{start}_match"] == "Waren (Müritz) (13000001)"
    assert rows["2"]["inferred_location_end_geocode"] == "exact"
    assert rows["2"]["inferred_location_end_match"] == "Beispielstadt (01000002)"
    assert rows["3"][f"{start}_geocode"] == "nearest_to_anchor"
    assert rows["3"][f"{start}_match"] == "Kirchberg (14000001)"
    assert rows["4"][f"{start}_geocode"] == "unresolved:no_match"
    assert rows["4"][f"{start}_lat"] == ""
    assert rows["5"][f"{start}_geocode"] == "skipped:code"
    assert rows["6"][f"{start}_geocode"] == "skipped:street_address"
    assert all(rows["7"][field] == "" for field in GEOCODE_FIELDS)
    assert rows["8"][f"{start}_geocode"] == "unresolved:ambiguous_no_anchor"


def test_match_without_ags_is_just_the_name() -> None:
    matcher = Matcher([place("9", "Ohnekey", "", 50.0, 10.0)], [])
    result = geocode_rows([record("1", "Ohnekey", "place")], matcher, 100.0, 3)
    assert result.rows[0]["inferred_location_start_match"] == "Ohnekey"
    assert result.features[0]["properties"]["match"] == "Ohnekey"


def test_input_rows_are_not_changed() -> None:
    geocode_rows(ROWS, MATCHER, 100, 3)
    assert "inferred_location_start_geocode" not in ROWS[0]


def test_report_and_unresolved_names() -> None:
    result = geocode_rows(ROWS, MATCHER, 100, 3)
    report = result.report
    assert (report["locations"], report["resolved"], report["resolved_share"]) == (8, 4, 0.5)
    assert report["by_dso"]["a"]["anchor"] == [51.06, 13.0]
    assert report["by_dso"]["a"]["anchor_points"] == 3
    assert report["by_dso"]["b"]["anchor"] is None
    assert report["by_kind"]["substation"] == {"resolved": 1, "total": 1}
    # Anchor of DSO a is (51.06, 13.0); Waren matched uniquely but lies ~272 km away.
    assert [item["name"] for item in report["far_from_dso"]] == ["Waren"]
    assert report["far_from_dso"][0]["distance_km"] > 100
    assert result.unresolved == [
        {
            "name": "Kirchberg",
            "kind": "place",
            "reason": "ambiguous_no_anchor",
            "count": 1,
            "dso_slugs": "b",
        },
        {"name": "Nirgendwo", "kind": "place", "reason": "no_match", "count": 1, "dso_slugs": "a"},
    ]


def test_features() -> None:
    result = geocode_rows(ROWS, MATCHER, 100, 3)
    assert len(result.features) == 4
    assert result.features[0] == {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [13.0, 51.0]},
        "properties": {
            "row_id": "1",
            "role": "start",
            "dso_slug": "a",
            "name": "Musterdorf",
            "match": "Musterdorf (01000001)",
            "geocode": "exact+station",
            "precision": "settlement",
        },
    }


START = "inferred_location_start"


def test_anchor_needs_exact_matches_and_counts_distinct_places() -> None:
    fallback_only = [
        record("1", "Gewerbegebiet, Musterdorf", "place", dso="c"),
        record("2", "Musterdorf Nord", "place", dso="c"),
        record("3", "Halle, Beispielstadt", "place", dso="c"),
        record("4", "Halle, Waren", "place", dso="c"),
    ]
    by_dso = geocode_rows(fallback_only, MATCHER, 100, 3).report["by_dso"]
    assert (by_dso["c"]["anchor"], by_dso["c"]["anchor_points"]) == (None, 0)

    repeated = [
        record("1", "Musterdorf", "place", dso="d"),
        record("2", "Musterdorf", "place", dso="d"),
        record("3", "Musterdorf", "place", dso="d"),
        record("4", "Beispielstadt", "place", dso="d"),
        record("5", "Waren", "place", dso="d"),
    ]
    by_dso = geocode_rows(repeated, MATCHER, 100, 3).report["by_dso"]
    assert by_dso["d"]["anchor_points"] == 3
    assert by_dso["d"]["anchor"] is not None


def test_unresolved_names_are_counted_across_dsos_and_sorted() -> None:
    rows = [
        record("1", "Anderswo", "place"),
        record("2", "Dort", "place"),
        record("3", "Dort", "place"),
        record("4", "Nirgendwo", "place"),
        record("5", "Nirgendwo", "place"),
        record("6", "Nirgendwo", "place", dso="b"),
    ]
    unresolved = geocode_rows(rows, MATCHER, 100, 3).unresolved
    assert [(item["name"], item["count"], item["dso_slugs"]) for item in unresolved] == [
        ("Nirgendwo", 3, "a,b"),
        ("Dort", 2, "a"),
        ("Anderswo", 1, "a"),
    ]


def test_far_from_dso_only_for_unique_matches_with_an_anchor() -> None:
    anchored = [
        record("1", "Musterdorf", "place"),
        record("2", "Beispielstadt", "place"),
        record("3", "Kirchberg", "place"),
    ]
    result = geocode_rows(anchored, MATCHER, 100, 2)
    assert result.rows[2][f"{START}_geocode"] == "nearest_to_anchor"
    assert result.report["far_from_dso"] == []
    # One place is below min_points, so there is no anchor and nothing to be far from.
    assert (
        geocode_rows([record("1", "Waren", "place")], MATCHER, 100, 3).report["far_from_dso"] == []
    )


def test_street_address_with_comma_uses_comma_part() -> None:
    rows = [
        record("1", "Hauptstraße 5, Musterdorf", "street_address"),
        record("2", "Hauptstr. 5, ", "street_address"),
        record("3", ",", "street_address"),
    ]
    result = geocode_rows(rows, MATCHER, 100, 3)
    assert [row[f"{START}_geocode"] for row in result.rows] == [
        "comma_part",
        "skipped:street_address",
        "skipped:street_address",
    ]


def test_no_rows() -> None:
    report = geocode_rows([], MATCHER, 100, 3).report
    assert (report["locations"], report["resolved_share"]) == (0, 0.0)


def test_names_without_letters_do_not_match() -> None:
    rows = [record("1", "", "place"), record("2", ",", "place"), record("3", "()", "place")]
    result = geocode_rows(rows, MATCHER, 100, 3)
    assert result.report["locations"] == 2  # an empty name is no location
    assert [row[f"{START}_geocode"] for row in result.rows] == [
        "",
        "unresolved:no_match",
        "unresolved:no_match",
    ]
