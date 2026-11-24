# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Matching grid objects by name, kind, operator and distance."""

import pytest

from nap_tool.geocoder.config import OsmSettings
from nap_tool.geocoder.match import distance_km
from nap_tool.geocoder.objects import GridObject, ObjectMatcher

SETTINGS = OsmSettings(
    classes=["substation", "plant"],
    kinds={"substation": ["substation"], "local_substation": ["substation"], "place": ["plant"]},
    rescue_only_kinds=["place"],
    strip_words=["umspannwerk", "uw", "kraftwerk"],
    operator_stop_words=["gmbh", "netz", "ag"],
    max_km=15,
)


def obj(
    object_id: str, cls: str, name: str, lat: float, lon: float, operator: str = ""
) -> GridObject:
    """A grid object without ref and voltage."""
    return GridObject(object_id, cls, name, operator, "", "", lat, lon)


OBJECTS = [
    obj("node/1", "substation", "Umspannwerk Musterdorf", 51.01, 13.01),
    obj("node/2", "substation", "UW Waren (Müritz)", 53.5, 12.7),
    obj("node/3", "substation", "Umspannwerk Neustadt", 51.05, 13.05, "Fremdnetz"),
    obj("node/4", "substation", "Umspannwerk Neustadt", 51.10, 13.10, "Musternetz GmbH"),
    obj("node/5", "plant", "Kraftwerk Beispiel", 52.0, 11.0),
    obj("node/6", "substation", "Umspannwerk Weit", 40.0, 10.0),
]
MATCHER = ObjectMatcher(OBJECTS, SETTINGS)
NEAR = (51.0, 13.0)


def test_station_names_match_without_station_words() -> None:
    hit = MATCHER.find("Musterdorf", "substation", NEAR, "")
    assert (hit.status, hit.place.id, hit.place.object_class, hit.place.source) == (
        "osm_substation",
        "node/1",
        "substation",
        "osm",
    )
    assert (hit.place.lat, hit.place.lon, hit.place.ags) == (51.01, 13.01, "")


def test_osm_names_are_also_found_without_qualifier() -> None:
    assert MATCHER.find("Waren", "substation", (53.4, 12.6), "").place.id == "node/2"


def test_operator_overlap_beats_distance() -> None:
    assert MATCHER.find("Neustadt", "substation", NEAR, "Musternetz Verteilnetz GmbH").place.id == (
        "node/4"
    )


def test_nearest_wins_without_operator_hint() -> None:
    assert MATCHER.find("Neustadt", "substation", NEAR, "Anderes Netz GmbH").place.id == "node/3"


def test_objects_beyond_max_km_are_ignored() -> None:
    assert MATCHER.find("Weit", "substation", NEAR, "") is None


def test_without_a_reference_point_nothing_matches() -> None:
    """A unique name anywhere in Germany is not plausible without a place to compare to."""
    assert MATCHER.find("Musterdorf", "substation", None, "") is None
    assert MATCHER.find("Neustadt", "substation", None, "") is None


def test_kind_selects_the_classes() -> None:
    assert MATCHER.find("Beispiel", "place", (52.0, 11.1), "").status == "osm_plant"
    assert MATCHER.find("Musterdorf", "place", NEAR, "") is None
    assert MATCHER.find("Beispiel", "substation", (52.0, 11.1), "") is None


def test_unconfigured_kind_and_empty_keys_do_not_match() -> None:
    assert MATCHER.find("Musterdorf", "street_address", NEAR, "") is None
    assert MATCHER.find("UW Umspannwerk", "substation", NEAR, "") is None


def test_rescue_only_kinds_are_exposed() -> None:
    assert MATCHER.rescue_only_kinds == {"place"}


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_names_do_not_match(name: str) -> None:
    assert MATCHER.find(name, "substation", NEAR, "") is None


def test_operator_preference_is_strict() -> None:
    """A same-named object of another operator nearby is likelier a different place."""
    matcher = ObjectMatcher(
        [
            obj("node/1", "substation", "Umspannwerk Ort", 51.0, 13.5, "Musternetz GmbH"),
            obj("node/2", "substation", "Umspannwerk Ort", 51.0, 13.01, "Fremdnetz"),
        ],
        SETTINGS,
    )
    assert distance_km(NEAR, (51.0, 13.5)) > SETTINGS.max_km
    assert matcher.find("Ort", "substation", NEAR, "Musternetz GmbH") is None


def test_object_exactly_at_max_km_still_matches() -> None:
    target = (51.0, 13.2)
    exact = distance_km(NEAR, target)
    settings = SETTINGS.model_copy(update={"max_km": exact})
    matcher = ObjectMatcher([obj("node/1", "substation", "Umspannwerk Ort", *target)], settings)
    assert matcher.find("Ort", "substation", NEAR, "").place.id == "node/1"


def test_equal_distance_lower_id_wins() -> None:
    matcher = ObjectMatcher(
        [
            obj("node/9", "substation", "Umspannwerk Ort", 51.01, 13.0),
            obj("node/2", "substation", "Umspannwerk Ort", 51.01, 13.0),
        ],
        SETTINGS,
    )
    assert matcher.find("Ort", "substation", NEAR, "").place.id == "node/2"


def test_strip_word_only_names_never_match_but_digits_can() -> None:
    matcher = ObjectMatcher(
        [
            obj("node/1", "substation", "Umspannwerk", 51.0, 13.0),
            obj("node/2", "substation", "110", 51.0, 13.0),
        ],
        SETTINGS,
    )
    assert matcher.find("Umspannwerk", "substation", NEAR, "") is None
    assert matcher.find("110", "substation", NEAR, "").place.id == "node/2"


def test_name_without_qualifier_is_not_indexed_twice() -> None:
    matcher = ObjectMatcher(
        [obj("node/1", "substation", "Umspannwerk Waren (Müritz)", 53.5, 12.7)], SETTINGS
    )
    assert matcher.find("Waren", "substation", (53.5, 12.7), "").place.id == "node/1"
    assert len(matcher.index["waren"]) == 1


def test_only_allowed_classes_count() -> None:
    matcher = ObjectMatcher(
        [
            obj("node/1", "plant", "Beispiel", 52.0, 11.0),
            obj("node/2", "substation", "Beispiel", 52.0, 11.0),
        ],
        SETTINGS,
    )
    assert matcher.find("Beispiel", "substation", (52.0, 11.0), "").place.id == "node/2"


def test_explicit_max_km_overrides_the_configured_limit() -> None:
    target = (51.36, 13.0)
    assert 35 < distance_km(NEAR, target) < 45
    matcher = ObjectMatcher([obj("node/1", "substation", "Umspannwerk Ort", *target)], SETTINGS)
    assert matcher.find("Ort", "substation", NEAR, "") is None
    assert matcher.find("Ort", "substation", NEAR, "", max_km=100).place.id == "node/1"
