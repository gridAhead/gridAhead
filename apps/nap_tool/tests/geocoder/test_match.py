# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Place data lookup steps, DSO anchors and candidate choice."""

import pytest

from nap_tool.geocoder.match import (
    Lookup,
    Matcher,
    Place,
    Resolution,
    choose,
    distance_km,
    dso_anchors,
)


def place(
    id: str, name: str, ags: str, lat: float, lon: float, population: int = 100, name2: str = ""
) -> Place:
    return Place(
        id=id,
        name=name,
        name2=name2,
        object_class="AX_Ortslage",
        ags=ags,
        lat=lat,
        lon=lon,
        population=population,
    )


PLACES = [
    place("1", "Musterdorf", "01000001", 51.0, 13.0),
    place("2", "Waren (Müritz)", "13000001", 53.5, 12.7),
    place("3", "Kirchberg", "14000001", 51.1, 13.1),
    place("4", "Kirchberg", "09000001", 48.0, 11.0),
    place("5", "Beispielstadt", "01000002", 51.05, 13.05, population=50),
    place("6", "Beispielstadt", "01000002", 51.06, 13.06, population=5000),
    place("7", "Schwarzach b. Kulmbach", "09000002", 50.1, 11.4, name2="Schwarzach bei Kulmbach"),
]
MATCHER = Matcher(PLACES, ["nord", "süd"])


def ids(lookup: Lookup) -> list[str]:
    return [candidate.id for candidate in lookup.candidates]


@pytest.mark.parametrize(
    ("name", "street", "step", "expected"),
    [
        ("Musterdorf", False, "exact", ["1"]),
        ("Waren", False, "exact", ["2"]),  # index alias without qualifier
        ("Schwarzach bei Kulmbach", False, "exact", ["7"]),  # NAME2
        ("Schwarzach", False, "exact", ["7"]),
        ("Gewerbegebiet X, Musterdorf", False, "comma_part", ["1"]),
        ("Musterdorf Nord", False, "strip_suffix", ["1"]),
        ("Musterdorf-Süd", False, "strip_suffix", ["1"]),
        ("Musterdorf (Kreis X)", False, "strip_qualifier", ["1"]),
        ("Hauptstraße 5, Musterdorf", True, "comma_part", ["1"]),
        ("Musterdorf", True, "", []),  # a street address tries only comma parts
        ("Nirgendwo", False, "", []),
        ("Kirchberg", False, "exact", ["3", "4"]),
    ],
)
def test_lookup_steps(name: str, street: bool, step: str, expected: list[str]) -> None:
    lookup = MATCHER.lookup(name, street)
    assert (lookup.step, ids(lookup)) == (step, expected)


def test_same_municipality_counts_once_most_populous_wins() -> None:
    assert ids(MATCHER.lookup("Beispielstadt")) == ["6"]


def test_choose_without_candidates() -> None:
    assert choose(Lookup("", ()), None, 100).status == "unresolved:no_match"


def test_choose_unique_keeps_step() -> None:
    resolution = choose(MATCHER.lookup("Musterdorf Nord"), None, 100)
    assert (resolution.status, resolution.place.id) == ("strip_suffix", "1")


def test_choose_ambiguous_without_anchor() -> None:
    status = choose(MATCHER.lookup("Kirchberg"), None, 100).status
    assert status == "unresolved:ambiguous_no_anchor"


def test_choose_ambiguous_nearest_to_anchor() -> None:
    resolution = choose(MATCHER.lookup("Kirchberg"), (51.0, 13.0), 100)
    assert (resolution.status, resolution.place.id) == ("nearest_to_anchor", "3")


def test_choose_ambiguous_too_far() -> None:
    status = choose(MATCHER.lookup("Kirchberg"), (54.5, 9.5), 100).status
    assert status == "unresolved:ambiguous_far"


def test_dso_anchor_is_median_and_needs_enough_points() -> None:
    anchors = dso_anchors({"a": {PLACES[0], PLACES[2], PLACES[5]}, "b": {PLACES[0]}}, 3)
    assert anchors == {"a": (51.06, 13.06)}


def test_distance_berlin_hamburg() -> None:
    assert distance_km((52.52, 13.405), (53.551, 9.993)) == pytest.approx(255, abs=3)


def test_places_without_ags_stay_distinct() -> None:
    matcher = Matcher(
        [place("8", "Einzelhof", "", 50.0, 10.0), place("9", "Einzelhof", "", 50.5, 10.5)], []
    )
    assert ids(matcher.lookup("Einzelhof")) == ["8", "9"]


def test_only_a_suffix_word_does_not_trigger_strip_suffix() -> None:
    matcher = Matcher([place("1", "Musterdorf", "01000001", 51.0, 13.0)], ["nord"])
    assert matcher.lookup("Nord").step == ""


def test_resolution_exposes_structured_fields() -> None:
    resolved = choose(MATCHER.lookup("Musterdorf"), None, 100)
    assert (resolved.kind, resolved.detail, resolved.status) == ("resolved", "exact", "exact")
    unresolved = choose(Lookup("", ()), None, 100)
    assert (unresolved.kind, unresolved.detail, unresolved.place) == (
        "unresolved",
        "no_match",
        None,
    )
    assert Resolution("skipped", "code").status == "skipped:code"
