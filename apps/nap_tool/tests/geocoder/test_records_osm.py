# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""OSM objects in row-level geocoding: upgrade, rescue, precision."""

from nap_tool.geocoder.config import OsmSettings
from nap_tool.geocoder.match import Matcher, Place
from nap_tool.geocoder.objects import GridObject, ObjectMatcher
from nap_tool.geocoder.records import geocode_rows

PLACES = [
    Place("1", "Musterdorf", "", "AX_Ortslage", "01000001", 51.0, 13.0, 100),
    Place("2", "Beispielstadt", "", "AX_Ortslage", "01000002", 51.05, 13.05, 500),
]
MATCHER = Matcher(PLACES, [])
OBJECTS = ObjectMatcher(
    [
        GridObject("node/1", "substation", "Umspannwerk Musterdorf", "", "", "", 51.01, 13.01),
        GridObject("node/2", "substation", "Umspannwerk Stegau", "", "", "", 51.02, 13.02),
        GridObject("way/3", "plant", "Kraftwerk Nirgendwo", "", "", "", 51.03, 13.03),
        GridObject("way/4", "plant", "Kraftwerk Beispielstadt", "", "", "", 51.06, 13.06),
    ],
    OsmSettings(
        kinds={"substation": ["substation"], "place": ["plant"]},
        rescue_only_kinds=["place"],
        strip_words=["umspannwerk", "kraftwerk"],
    ),
)


def record(row_id: str, start: str, kind: str, dso: str = "a") -> dict[str, str]:
    return {
        "row_id": row_id,
        "dso_slug": dso,
        "dso_name": "Musternetz GmbH",
        "inferred_record_type": "measure",
        "inferred_location_start": start,
        "inferred_location_start_kind": kind,
        "inferred_location_end": "",
        "inferred_location_end_kind": "",
    }


ROWS = [
    record("1", "Musterdorf", "substation"),  # settlement exact -> upgraded to the OSM object
    record("2", "Stegau", "substation"),  # not in GN250 -> rescued via DSO anchor
    record("3", "Musterdorf", "place"),  # rescue-only kind: settlement stays
    record("4", "Nirgendwo", "place"),  # unresolved -> rescued by a plant
    record("5", "Beispielstadt", "place"),  # resolved; the plant must not replace it
    record("6", "Unbekannt", "substation"),  # nothing anywhere
]


def by_id(result) -> dict[str, dict[str, str]]:
    return {row["row_id"]: row for row in result.rows}


def test_upgrade_rescue_and_rescue_only_rules() -> None:
    rows = by_id(geocode_rows(ROWS, MATCHER, 100, 1, OBJECTS))
    s = "inferred_location_start"
    assert (rows["1"][f"{s}_geocode"], rows["1"][f"{s}_precision"]) == ("osm_substation", "object")
    assert rows["1"][f"{s}_match"] == "Umspannwerk Musterdorf"
    assert (rows["1"][f"{s}_lat"], rows["1"][f"{s}_lon"]) == ("51.010000", "13.010000")
    assert (rows["2"][f"{s}_geocode"], rows["2"][f"{s}_precision"]) == ("osm_substation", "object")
    assert (rows["3"][f"{s}_geocode"], rows["3"][f"{s}_precision"]) == ("exact", "settlement")
    assert (rows["4"][f"{s}_geocode"], rows["4"][f"{s}_precision"]) == ("osm_plant", "object")
    assert (rows["5"][f"{s}_geocode"], rows["5"][f"{s}_precision"]) == ("exact", "settlement")
    assert rows["6"][f"{s}_geocode"] == "unresolved:no_match"
    assert rows["6"][f"{s}_precision"] == ""


def test_report_counts_matches_and_rescues() -> None:
    result = geocode_rows(ROWS, MATCHER, 100, 1, OBJECTS)
    assert result.report["osm"] == {"matched": 3, "rescued": 2}
    assert result.report["by_status"]["osm_substation"] == 2


def test_features_carry_precision_and_osm_points_are_not_far_from_dso() -> None:
    result = geocode_rows(ROWS, MATCHER, 100, 1, OBJECTS)
    precisions = {f["properties"]["row_id"]: f["properties"]["precision"] for f in result.features}
    assert precisions["1"] == "object" and precisions["3"] == "settlement"
    assert all(item["row_id"] not in {"1", "2", "4"} for item in result.report["far_from_dso"])


def test_without_objects_nothing_changes_except_empty_precision_for_unresolved() -> None:
    rows = by_id(geocode_rows(ROWS, MATCHER, 100, 1))
    s = "inferred_location_start"
    assert rows["1"][f"{s}_geocode"] == "exact+station"
    assert rows["1"][f"{s}_precision"] == "settlement"
    assert rows["6"][f"{s}_precision"] == ""
    assert geocode_rows(ROWS, MATCHER, 100, 1).report["osm"] == {"matched": 0, "rescued": 0}


ANCHOR_PLACES = [
    Place("10", "Adorf", "", "AX_Ortslage", "02000001", 51.0, 13.0, 100),
    Place("11", "Bdorf", "", "AX_Ortslage", "02000002", 51.0, 13.01, 100),
    Place("12", "Cdorf", "", "AX_Ortslage", "02000003", 51.01, 13.0, 100),
]
FAR_OBJECT = ObjectMatcher(  # about 40 km north of the anchor of DSO "a"
    [GridObject("node/9", "substation", "Umspannwerk Fernau", "", "", "", 51.36, 13.0)],
    OsmSettings(kinds={"substation": ["substation"]}, strip_words=["umspannwerk"]),
)
FERNAU_ROWS = [
    record("1", "Adorf", "place"),
    record("2", "Bdorf", "place"),
    record("3", "Cdorf", "place"),
    record("4", "Fernau", "substation"),
]


def test_anchor_rescue_uses_the_anchor_distance() -> None:
    rows = by_id(geocode_rows(FERNAU_ROWS, Matcher(ANCHOR_PLACES, []), 100, 3, FAR_OBJECT))
    assert rows["4"]["inferred_location_start_geocode"] == "osm_substation"


def test_settlement_point_keeps_the_osm_distance() -> None:
    fernau = Place("13", "Fernau", "", "AX_Ortslage", "02000004", 51.0, 13.0, 100)
    matcher = Matcher([*ANCHOR_PLACES, fernau], [])
    rows = by_id(geocode_rows(FERNAU_ROWS, matcher, 100, 3, FAR_OBJECT))
    assert rows["4"]["inferred_location_start_geocode"] == "exact+station"
