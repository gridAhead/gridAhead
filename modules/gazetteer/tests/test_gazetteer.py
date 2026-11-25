# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""End to end: gazetteer-build on tiny fixtures, then gazetteer match."""

import json
import sqlite3
from contextlib import closing

import gazetteer_build
import pytest
from conftest import DSO_1, DSO_2, PLACES, write_inputs

import gazetteer


def match(capsys, *arguments: str) -> list[dict]:
    """Run `gazetteer match` and return its JSON lines."""
    gazetteer.main(["match", *arguments])
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def names(result: dict) -> list[str]:
    return [candidate["name"] for candidate in result["candidates"]]


def test_build_writes_gazetteer_into_data_dir(built):
    assert (built / "gazetteer" / "gazetteer.sqlite").is_file()


def test_match_returns_only_candidates_inside_the_dso_area(built, capsys):
    [inside] = match(capsys, "--dso", DSO_2, "Fernau")
    [outside] = match(capsys, "--dso", DSO_1, "Fernau")

    assert inside["q"] == "Fernau"
    assert names(inside)[0] == "Fernau"
    assert "Fernau" not in names(outside)


def test_level_restricts_to_that_levels_area_and_no_level_covers_the_union(built, capsys):
    [medium_voltage] = match(capsys, "--dso", DSO_1, "--level", "MV", "Dogern")
    [union] = match(capsys, "--dso", DSO_1, "Dogern")

    assert "Dogern" not in names(medium_voltage)
    assert names(union)[0] == "Dogern"
    [other_dso] = match(capsys, "--dso", DSO_2, "Dogern")
    assert names(other_dso)[0] == "Dogern"


def test_kind_restricts_to_places_or_stations(built, capsys):
    [stations] = match(capsys, "--dso", DSO_1, "--kind", "station", "Albbruck")
    [places] = match(capsys, "--dso", DSO_1, "--kind", "place", "Albbruck")

    assert {candidate["kind"] for candidate in stations["candidates"]} == {"station"}
    assert {candidate["kind"] for candidate in places["candidates"]} == {"place"}


@pytest.mark.parametrize(
    "query,kind,expected",
    [
        ("UW Albbruck", "station", "Albbruck"),
        ("Umspannwerk  albbruck", "station", "Albbruck"),
        ("ONS Albbruck", "station", "Albbruck"),
        ("UW-Albbruck", "station", "Albbruck"),
        ("Hochfeld", "station", "Umspannwerk Hochfeld"),
        ("GROSSWEILER", "place", "Großweiler"),
        ("großweiler", "place", "Großweiler"),
    ],
)
def test_normalization_ignores_case_eszett_whitespace_and_station_prefixes(
    built, capsys, query, kind, expected
):
    [result] = match(capsys, "--dso", DSO_1, "--kind", kind, query)

    assert result["candidates"][0]["name"] == expected
    assert result["candidates"][0]["score"] == 100


@pytest.mark.parametrize("query", ["Kiesenbach", "Albbruck Süd", "Albbruck 1"])
def test_alternative_station_names_match(built, capsys, query):
    [result] = match(capsys, "--dso", DSO_1, "--kind", "station", query)

    assert result["candidates"][0]["name"] == "Albbruck"
    assert result["candidates"][0]["score"] == 100


def test_candidates_carry_kind_specific_fields(built, capsys):
    [result] = match(capsys, "--dso", DSO_1, "-n", "2", "Albbruck")

    assert sorted(result["candidates"], key=lambda candidate: candidate["kind"]) == [
        {"name": "Albbruck", "kind": "place", "score": 100, "osm": "node/1", "place_type": "town"},
        {
            "name": "Albbruck",
            "kind": "station",
            "score": 100,
            "osm": "way/11",
            "voltage": "110000;20000",
            "operator": "Netze Eins",
        },
    ]


def test_results_are_ranked_by_score_and_limited_to_n_with_default_5(built, capsys):
    [default] = match(capsys, "--dso", DSO_1, "--kind", "place", "Weiler 3")
    [limited] = match(capsys, "--dso", DSO_1, "--kind", "place", "-n", "2", "Weiler 3")
    [everything] = match(capsys, "--dso", DSO_1, "--kind", "place", "-n", "100", "Weiler 3")

    assert len(default["candidates"]) == 5
    assert len(limited["candidates"]) == 2
    assert names(limited)[0] == "Weiler 3"
    scores = [candidate["score"] for candidate in everything["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert len(scores) > 5


def test_several_names_give_one_line_each_in_input_order(built, capsys):
    results = match(capsys, "--dso", DSO_1, "Dogern", "Albbruck", "Dogern")

    assert [result["q"] for result in results] == ["Dogern", "Albbruck", "Dogern"]
    assert [names(result)[0] for result in results] == ["Dogern", "Albbruck", "Dogern"]


def test_no_match_gives_an_empty_candidate_list(built, capsys):
    [no_stations] = match(capsys, "--dso", DSO_2, "--kind", "station", "Albbruck")
    [nothing_alike] = match(capsys, "--dso", DSO_2, "--kind", "place", "Xyz")

    assert no_stations == {"q": "Albbruck", "candidates": []}
    assert nothing_alike == {"q": "Xyz", "candidates": []}


def test_missing_gazetteer_names_the_build_command(data_dir, capsys):
    with pytest.raises(SystemExit) as error:
        gazetteer.main(["match", "--dso", DSO_1, "Albbruck"])

    assert "gazetteer-build" in str(error.value)
    assert not (data_dir / "gazetteer" / "gazetteer.sqlite").exists()


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--dso", "SNB999999999999"], "SNB999999999999"),
        (["--dso", DSO_2, "--level", "HV"], "HV"),
    ],
)
def test_unknown_dso_or_level_is_an_error(built, capsys, arguments, message):
    with pytest.raises(SystemExit) as error:
        gazetteer.main(["match", *arguments, "Albbruck"])

    assert message in str(error.value)
    assert capsys.readouterr().out == ""


def test_rebuild_leaves_no_stale_entries(built, tmp_path, capsys):
    gazetteer_build.main(write_inputs(tmp_path, places=PLACES[1:]))
    capsys.readouterr()

    [result] = match(capsys, "--dso", DSO_1, "--kind", "place", "-n", "100", "Albbruck")

    assert "Albbruck" not in names(result)


def test_build_records_source_snapshot_dates(built):
    with closing(sqlite3.connect(built / "gazetteer" / "gazetteer.sqlite")) as connection:
        dates = dict(connection.execute("SELECT name, snapshot_date FROM source"))

    assert dates == {"places": "2026-11-01", "stations": "2026-11-02", "dso_areas": "2026-10-01"}


def test_build_accepts_an_input_without_entries(data_dir, tmp_path, capsys):
    gazetteer_build.main(write_inputs(tmp_path, stations=[]))
    capsys.readouterr()

    [result] = match(capsys, "--dso", DSO_1, "--kind", "station", "Albbruck")

    assert result["candidates"] == []


def test_relative_data_dir_works(built, monkeypatch, capsys):
    monkeypatch.chdir(built.parent)
    monkeypatch.setenv("NAP_DATA_DIR", built.name)

    [result] = match(capsys, "--dso", DSO_1, "Albbruck")

    assert names(result)[0] == "Albbruck"


@pytest.mark.parametrize("count", ["0", "-1"])
def test_n_must_be_positive(built, capsys, count):
    with pytest.raises(SystemExit):
        gazetteer.main(["match", "--dso", DSO_1, "-n", count, "Albbruck"])

    assert capsys.readouterr().out == ""
