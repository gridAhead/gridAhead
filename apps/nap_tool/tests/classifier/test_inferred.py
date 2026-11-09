"""Inferred columns for NAP 2026 measure lists: asset codes, level lists, locations, quality."""

import json

import pytest

from nap_tool.classifier import classify
from nap_tool.classifier.config import ClassifyConfig, load_config
from nap_tool.classifier.rules import asset_codes


@pytest.fixture
def config():
    return load_config()


def row(name="Testmaßnahme", number=1, **values):
    return dict(
        dso_slug=values.pop("dso_slug", "example"),
        measure_name=name,
        subgrid_area=values.pop("subgrid_area", "Testnetz"),
        source_cells_json=json.dumps(
            {"origin": dict(extract_table_id=12, row_number=number), "sources": []}
        ),
        **values,
    )


def classified(config, **values):
    return classify([row(**values)], config, {}).rows[0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("501", ["501"]),
        ("501. 601. 701", ["501", "601", "701"]),
        ("401, 801", ["401", "801"]),
        ("501 / 701", ["501", "701"]),
        ("301.401", ["301", "401"]),
        ("201401", ["201", "401"]),
        ("701, 501", ["701", "501"]),
        ("MS-Kabel", None),
        ("630 Kabel", None),
        ("1234", None),
    ],
)
def test_asset_code_cells(config, value, expected):
    assert asset_codes(value, config) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            dict(asset_type="501. 601. 701", grid_level="MS"),
            dict(
                inferred_grid_level="MV,MV/LV,LV",
                inferred_asset_types="line_or_cable,local_substation",
                inferred_asset_class="line",
                inferred_voltage=",,400",
            ),
        ),
        (
            dict(asset_type="701, 501", grid_level="NS"),
            dict(inferred_grid_level="LV,MV", inferred_voltage="400,"),
        ),
        (
            dict(asset_type="301, 401, 801", grid_level="UW HS auf MS"),
            dict(
                inferred_grid_level="HV/MV,HV",
                inferred_asset_types="substation,line_or_cable,secondary_tech",
            ),
        ),
        (
            dict(asset_type="401", grid_level="UW HS auf MS", name="UW Nord 110/20 kV"),
            dict(inferred_grid_level="HV/MV", inferred_voltage="110000/20000"),
        ),
        (
            dict(asset_type="301", line_construction_type="Freileitung"),
            dict(inferred_asset_type="overhead_line", inferred_grid_level="HV"),
        ),
        (
            dict(asset_type="301", line_construction_type="Erdkabel"),
            dict(inferred_asset_type="cable", inferred_voltage="110000"),
        ),
        (
            dict(asset_type="701", name="Netzerweiterung Musterdorf"),
            dict(inferred_asset_type="line_or_cable", inferred_quality_classification="medium"),
        ),
        (
            dict(asset_type="401", name="UW_Süd_Neubau_110-/20-kV_Umspannwerk"),
            dict(inferred_asset_type="substation", inferred_voltage="110000/20000"),
        ),
    ],
)
def test_codes_give_level_lists_and_aligned_voltages(config, values, expected):
    actual = classified(config, **values)
    for key, value in expected.items():
        assert actual[key] == value, key


def test_codes_only_add_assets_of_another_class(config):
    actual = classified(config, name="Kabelerneuerung Hauptstraße", asset_type="501. 601")
    assert actual["inferred_asset_types"] == "cable,local_substation"
    assert actual["inferred_asset_type"] == "cable"
    assert "asset_type_from_codes" not in actual["inferred_flags"].split(",")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Netzerweiterung; UW Lärchenstraße (1.BA)", "substation"),
        ("Neue Anbindung Zell-Weierbach ab UA Elgersweier", "line_or_cable"),
        ("Netzentwicklung Raum Nord", "network"),
        ("Netzentwicklung Raum Nord, Kabel", "cable"),
    ],
)
def test_streets_are_not_lines_and_network_is_a_fallback(config, name, expected):
    assert classified(config, name=name)["inferred_asset_type"] == expected


def test_reported_level_matching_its_station_phrase_is_no_conflict(config):
    actual = classified(
        config,
        name="NAP Maßnahme",
        measure_description="Laufende UW MS auf NS Maßnahme",
        asset_type="601",
        grid_level="UW MS auf NS",
    )
    assert actual["inferred_grid_level"] == "MV/LV"
    assert "grid_level_conflict" not in actual["inferred_flags"]
    assert actual["inferred_location_start"] == ""


@pytest.mark.parametrize(
    "name",
    [
        "Kleinstmaßnahmen Neubau 2024-2028 NC Niebüll",
        "Verstärkung MS-Kabel Maßnahmenregion 26",
        "SAMMLER: Ortsnetzstation - Netzoptimierung",
        "Vorhaben Umspannwerke < 250TEUR 2027",
    ],
)
def test_collective_measures_get_no_location(config, name):
    values = dict(measure_description="diverse Einzelmaßnahmen") if "Vorhaben" in name else {}
    actual = classified(config, name=name, **values)
    assert actual["inferred_record_type"] == "collective"
    assert actual["inferred_location_start"] == ""
    assert actual["inferred_quality_location"] == "not_applicable"


def test_reference_rows_get_no_location(config):
    actual = classified(config, name="Ersetzt durch lfd. Nr. 278")
    assert actual["inferred_location_start"] == ""
    assert actual["inferred_quality_location"] == "not_applicable"
    assert "refers_to_other_measure" in actual["inferred_flags"].split(",")


def test_footer_and_blank_rows_are_dropped_and_reported(config):
    sources = [
        row("UW Nord", 1, measure_no="7"),
        row("Excel Datei unter der Lizenz: CC BY 4.0", 2, subgrid_area=""),
        row("", 3, subgrid_area="", measure_no="17"),
        row("", 4, subgrid_area=""),
    ]
    result = classify(sources, config, {})
    assert [item["row_id"] for item in result.rows] == ["12-1"]
    assert [item["row_id"] for item in result.report["dropped_rows"]] == ["12-2", "12-3", "12-4"]


@pytest.mark.parametrize(
    ("name", "description", "expected"),
    [
        (
            "Trafotausch UW Krugzell",
            "",
            dict(inferred_location_start="Krugzell", inferred_location_start_kind="substation"),
        ),
        (
            "Neuer HöS/HS-Knoten im Suchraum Amberg",
            "",
            dict(inferred_location_start="Amberg", inferred_location_start_kind="search_area"),
        ),
        (
            "Neubau UW (Suchraum Wittstock)",
            "",
            dict(inferred_location_start="Wittstock", inferred_location_start_kind="search_area"),
        ),
        (
            "Am Herrengarten 071a- Siegburger Str.297",
            "Leitungserneuerung zwischen den Knoten Am Herrengarten 071a-Siegburger Str.297",
            dict(
                inferred_location_start="Am Herrengarten 071a",
                inferred_location_start_kind="street_address",
                inferred_location_end="Siegburger Str.297",
            ),
        ),
        (
            "20KV-Verkabelung Rheinböllen_Daxweiler_Abzw Stromhütte-Heide",
            "",
            dict(
                inferred_location_start="Rheinböllen",
                inferred_location_end="Heide",
                inferred_quality_location="medium",
            ),
        ),
        (
            "Austausch sanierter PE/VPE Kabelabschnitten in Wartekuppe",
            "",
            dict(inferred_location_start="Wartekuppe", inferred_asset_type="cable"),
        ),
        (
            "FLM: Langholt - Völlen",
            "",
            dict(
                inferred_location_start="Langholt",
                inferred_location_end="Völlen",
                inferred_quality_location="high",
            ),
        ),
        (
            "Netzentwicklung Raum München Nord I - Einführung zwei neuer Stromkreise in das UW "
            "Unterschleißheim",
            "",
            dict(inferred_asset_type="substation", inferred_location_start="Unterschleißheim"),
        ),
        ("NAP Maßnahme", "", dict(inferred_location_start="", inferred_quality_location="none")),
        (
            "Bergstrasse 46-48",
            "",
            dict(
                inferred_location_start="Bergstrasse 46-48",
                inferred_location_start_kind="street_address",
            ),
        ),
        ("Kabelverlegung (UW Breitungen)", "", dict(inferred_location_start="Breitungen")),
    ],
)
def test_locations_and_kinds(config, name, description, expected):
    actual = classified(config, name=name, measure_description=description)
    for key, value in expected.items():
        assert actual[key] == value, key


def test_object_references_and_comma_lists(config):
    actual = classified(config, name="110kV Seilauswechslung N1 Bl. 2473")
    assert actual["inferred_object_ref"] == "N1,Bl. 2473"
    assert ";" not in actual["inferred_flags"]


def test_route_without_asset_word_on_a_line_level_is_a_line(config):
    actual = classified(config, name="ENB: Bassum-Weyhe", grid_level="HS")
    assert actual["inferred_asset_type"] == "line_or_cable"
    assert "asset_type_from_grid_level" in actual["inferred_flags"].split(",")
    assert (actual["inferred_location_start"], actual["inferred_location_end"]) == (
        "Bassum",
        "Weyhe",
    )


def test_quality_grades(config):
    rows = [
        row("110 kV Freileitung Langholt - Völlen", 1, grid_level="HS"),
        row("Netzerweiterung", 2, asset_type="501"),
        row("2020-035", 3),
    ]
    result = classify(rows, config, {}).rows
    assert [item["inferred_quality_classification"] for item in result] == [
        "high",
        "medium",
        "none",
    ]
    assert result[0]["inferred_quality_location"] == "high"
    assert result[2]["inferred_quality_location"] == "none"


def test_case_folded_patterns_must_not_contain_sharp_s(config):
    settings = config.model_dump()
    settings["record_type"]["collective"].append("kleinstmaßnahm")
    with pytest.raises(ValueError, match="instead of 'ß'"):
        ClassifyConfig.model_validate(settings)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            dict(
                name="28_LK AK_84, Austausch NKBA 50, ST Mühlenstr. > ST Bergstr.", asset_type="501"
            ),
            dict(
                inferred_asset_type="cable",
                inferred_location_start="Mühlenstr.",
                inferred_location_end="Bergstr.",
            ),
        ),
        (
            dict(name="28_LKKS_45, Austausch NA2XS(F)2Y 150, UW WP. ISTHA", asset_type="501"),
            dict(inferred_asset_type="cable"),
        ),
        (
            dict(name="2 x Kabel US Hattingen - US Henrichshütte", asset_type="301"),
            dict(inferred_asset_type="cable", inferred_location_end="Henrichshütte"),
        ),
        (
            dict(
                name="28_LK_SEHR_106, Trassenbau UW Neumorschen - STL Bahnunterführung",
                asset_type="501",
            ),
            dict(inferred_asset_class="line", inferred_location_start="Neumorschen"),
        ),
        (
            dict(name="Kaiserstraße 25 - Karcherstr. 1", asset_type="501"),
            dict(inferred_asset_type="line_or_cable", inferred_location_end="Karcherstr. 1"),
        ),
    ],
)
def test_cable_designations_and_station_route_ends_follow_the_line(config, values, expected):
    actual = classified(config, **values)
    for key, value in expected.items():
        assert actual[key] == value, key


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (dict(name="ST Mühlenstr.", asset_type="601"), "local_substation"),
        (
            dict(name="SST Münchweiler Rodalb", asset_type="501", grid_level="MS"),
            "switching_station",
        ),
        (
            dict(name="US Oelkinghausen", asset_type="301, 401, 801", grid_level="UW HS auf MS"),
            "substation",
        ),
        (dict(name="MN UW Allendorf Nord-SST Neustadt, 1.BA", asset_type="501"), "line_or_cable"),
        (
            dict(name="10-kV-Netzanschaltung UW GUE", asset_type="501", grid_level="MS"),
            "substation",
        ),
    ],
)
def test_a_single_named_station_stays_the_object(config, values, expected):
    assert classified(config, **values)["inferred_asset_type"] == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Förste, ONS Schule\nEinschleifung NS-Kabel", "Schule"),
        ("Bartolfelde, Tilsiter Str., ONS Steinweg\nEinschleifung NS-Kabel", "Steinweg"),
        ("Kabelverlegung (UW Breitungen)", "Breitungen"),
    ],
)
def test_only_the_first_word_after_a_station_keyword_skips_stop_suffixes(config, name, expected):
    assert classified(config, name=name)["inferred_location_start"] == expected


def test_explicit_voltage_on_another_level_beats_the_default(config):
    actual = classified(config, name="220 kV Leitung Asslar - Dillenburg", grid_level="HS")
    assert actual["inferred_voltage"] == "220000"
    assert "voltage_other_level" in actual["inferred_flags"].split(",")
    plain = classified(config, name="Leitung Asslar - Dillenburg", grid_level="HS")
    assert plain["inferred_voltage"] == "110000"
