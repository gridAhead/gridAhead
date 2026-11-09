# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Observable classifications from literal real-world source rows."""

import json

import pytest

from nap_tool.classifier import classify
from nap_tool.classifier.config import load_config
from nap_tool.classifier.validation import markdown_report


@pytest.fixture
def config():
    return load_config()


def row(name="Testmaßnahme", number=1, **values):
    return dict(
        dso_slug=values.pop("dso_slug", "example"),
        measure_name=values.pop("measure_name", name),
        subgrid_area=values.pop("subgrid_area", "Testnetz"),
        source_cells_json=json.dumps(
            {
                "origin": dict(
                    extract_table_id=12,
                    row_number=number,
                    document_id=7,
                    clean_is_confirmed=True,
                    currentFrom="2024-04-30",
                ),
                "sources": [],
            }
        ),
        **values,
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            row("110 kV Freileitungsbau"),
            dict(
                inferred_asset_type="overhead_line",
                inferred_grid_level="HV",
                inferred_voltage="110000",
            ),
        ),
        (
            row("1 kV Kabel"),
            dict(inferred_asset_type="cable", inferred_grid_level="LV", inferred_voltage="400"),
        ),
        (
            row("Trafotausch UW Krugzell"),
            dict(
                inferred_asset_type="transformer",
                inferred_measure_type="replacement",
                inferred_location_start="Krugzell",
                inferred_location_start_kind="substation",
            ),
        ),
        (
            row("110kV Seilauswechslung N1"),
            dict(
                inferred_asset_type="line_component",
                inferred_grid_level="HV",
                inferred_measure_type="optimization",
            ),
        ),
        (
            row("ENB: UW Conneforde"),
            dict(
                inferred_asset_type="substation",
                inferred_grid_level="HV/MV",
                inferred_measure_type="replacement",
                inferred_location_start="Conneforde",
            ),
        ),
        (
            row("Neutraubling UW - Ersatzneubau"),
            dict(
                inferred_asset_type="substation",
                inferred_location_start="Neutraubling",
                inferred_measure_type="replacement",
            ),
        ),
        (
            row("80°C-Trassierung + FLM: Blexen-Grebswarden"),
            dict(
                inferred_asset_type="overhead_line",
                inferred_measure_type="optimization",
                inferred_location_start="Blexen",
                inferred_location_end="Grebswarden",
            ),
        ),
        (
            row("FLM: Langholt - Völlen"),
            dict(
                inferred_asset_type="overhead_line",
                inferred_location_start="Langholt",
                inferred_location_end="Völlen",
            ),
        ),
        (
            row("4-syst. Ausbau/ENB: Emden Borsum - Emden West"),
            dict(
                inferred_asset_type="overhead_line",
                inferred_measure_type="replacement",
                inferred_location_start="Emden Borsum",
                inferred_location_end="Emden West",
            ),
        ),
        (
            row("UW: Kompensationsspule in Hüttenrode"),
            dict(
                inferred_asset_type="earth_fault_compensation",
                inferred_grid_level="HV/MV",
                inferred_location_start="Hüttenrode",
            ),
        ),
        (
            row("Errichtung einer HS-Kompensationsspule"),
            dict(
                inferred_asset_type="earth_fault_compensation",
                inferred_grid_level="HV",
                inferred_measure_type="new",
            ),
        ),
        (
            row("Blindleistungsanlage UW Grohnde"),
            dict(
                inferred_asset_type="reactive_power_compensation",
                inferred_grid_level="HV/MV",
                inferred_location_start="Grohnde",
            ),
        ),
        (
            row("Neuer HöS/HS-Knoten im Suchraum Amberg"),
            dict(
                inferred_asset_type="substation",
                inferred_grid_level="EHV/HV",
                inferred_measure_type="new",
                inferred_location_start="Amberg",
            ),
        ),
        (
            row("110/10-kV-Station Kirchhörde"),
            dict(
                inferred_asset_type="substation",
                inferred_grid_level="HV/MV",
                inferred_voltage="110000/10000",
                inferred_location_start="Kirchhörde",
            ),
        ),
        (
            row("SST Kröning"),
            dict(
                inferred_asset_type="switching_station",
                inferred_location_start="Kröning",
                inferred_location_start_kind="switching_station",
            ),
        ),
        (
            row("28_HX_7, LS UW Borgholz, Borgholz"),
            dict(
                inferred_asset_type="switchgear",
                inferred_location_start="Borgholz",
                inferred_location_start_kind="substation",
            ),
        ),
        (
            row("28_Gö St_15, Austausch NAEKBA 120, SST Elliehäuser Weg > ST Münch"),
            dict(
                inferred_asset_type="cable",
                inferred_measure_type="replacement",
                inferred_location_start="Elliehäuser Weg",
                inferred_location_end="Münch",
            ),
        ),
        (
            row("Erneuerung Poppelsdorf"),
            dict(inferred_measure_type="replacement", inferred_location_start="Poppelsdorf"),
        ),
        (
            row(
                "Am Herrengarten 071a- Siegburger Str.297",
                measure_description=(
                    "Leitungserneuerung zwischen den Knoten Am Herrengarten 071a-Siegburger Str.297"
                ),
            ),
            dict(
                inferred_asset_type="line_or_cable",
                inferred_measure_type="replacement",
                inferred_location_start="Am Herrengarten 071a",
                inferred_location_end="Siegburger Str.297",
            ),
        ),
        (
            row("noch nicht benannte Vorhaben: zusätzliche HS/MS-UW"),
            dict(inferred_record_type="collective", inferred_location_start=""),
        ),
        (row("2020-035"), dict(inferred_asset_type="", inferred_location_start="")),
        (
            row("HSL Falkenberg - Herzberg - Jessen/Nord"),
            dict(
                inferred_location_start="Falkenberg",
                inferred_location_via="Herzberg",
                inferred_location_end="Jessen/Nord",
            ),
        ),
        (
            row("UW Weilheim - Ersatzneubau"),
            dict(inferred_location_start="Weilheim", inferred_location_end=""),
        ),
    ],
)
def test_real_measures(config, source, expected):
    actual = classify([source], config, {}).rows[0]
    for field, value in expected.items():
        assert actual[field] == value
    for field, value in source.items():
        assert actual[field] == value


@pytest.mark.parametrize(
    ("values", "expected", "flags"),
    [
        (
            dict(project_category="netzoptimieru ng und verstärkung"),
            dict(inferred_project_category="optimization"),
            [],
        ),
        (
            dict(project_category="unreadable interleaved text"),
            dict(inferred_project_category=""),
            ["unmapped:project_category"],
        ),
        (
            dict(
                project_category=(
                    "Ersatz(neubau) mit Erhöhung der Übertragungskapazität; "
                    "Netzoptimierung und -verstärkung"
                )
            ),
            dict(inferred_measure_type="replacement_increase"),
            [],
        ),
        (dict(grid_level="3, 4", asset_type="UW"), dict(inferred_grid_level="HV,HV/MV"), []),
        (dict(grid_level="3, 4", asset_type="Kabel"), dict(inferred_grid_level="HV,HV/MV"), []),
        (
            dict(grid_level="UW HS auf MS", asset_type="20-kV-Kabel"),
            dict(inferred_grid_level="HV/MV", inferred_voltage="110000/20000"),
            [],
        ),
        (
            dict(grid_level="UW HS auf MS", asset_type="Kabel"),
            dict(inferred_grid_level="HV/MV", inferred_voltage=""),
            [],
        ),
        (dict(grid_level="MS", asset_type="_24kv Kabel"), dict(inferred_voltage="20000"), []),
        (
            dict(grid_level="MS", asset_type="10-kV-Kabel, 1kV-Kabel"),
            dict(inferred_voltage="10000"),
            [],
        ),
        (dict(asset_type="630 Kabel"), dict(inferred_voltage=""), []),
        (
            dict(asset_type="Kabel", capacity_change_mva="-5"),
            dict(inferred_line_capacity_change_mva="-5"),
            [],
        ),
        (
            dict(asset_type="Trafo", capacity_change_mva="0", measure_name="Tausch"),
            dict(
                inferred_station_capacity_change_mva="0",
                inferred_measure_type="replacement_no_increase",
            ),
            [],
        ),
        (
            dict(asset_type="Trafo", capacity_change_mva="40", measure_name="Tausch"),
            dict(
                inferred_station_capacity_change_mva="40",
                inferred_measure_type="replacement_increase",
            ),
            [],
        ),
        (
            dict(asset_type="Eigenbedarf", capacity_change_mva="4"),
            dict(inferred_station_capacity_change_mva="", inferred_line_capacity_change_mva=""),
            ["capacity_unassigned"],
        ),
        (
            dict(asset_type="Trafo", capacity_change_mva="min. 0,075", planned_start="Jan 29"),
            dict(inferred_station_capacity_change_mva=""),
            ["unresolved:capacity_change_mva", "unresolved:planned_start"],
        ),
        (
            dict(asset_type="UW", aggregate_amount_eur="8000000"),
            dict(
                inferred_record_type="overview",
                inferred_asset_type="",
                inferred_grid_level="",
                inferred_location_start="",
            ),
            [],
        ),
        (dict(aggregate_period="2023 bis 2028 (T+5)"), dict(inferred_record_type="overview"), []),
        (dict(aggregate_amount_eur=""), dict(inferred_record_type="measure"), []),
        (
            dict(measure_name="Ersatz Tr101 (40 MVA)", planned_period_raw="2026"),
            dict(inferred_record_type="measure"),
            [],
        ),
        (
            dict(investment_2024_eur="500", measure_name=""),
            dict(inferred_record_type="overview"),
            [],
        ),
        (
            dict(grid_level="HS", asset_type="20 kV Kabel"),
            dict(inferred_grid_level="HV"),
            ["grid_level_conflict"],
        ),
        (dict(grid_level="HS"), dict(inferred_voltage="110000"), ["voltage_inferred"]),
        (
            dict(project_status="Maßnahme verworfen"),
            dict(inferred_project_status="dropped", inferred_record_type="measure"),
            [],
        ),
    ],
)
def test_derivation_and_flags(config, values, expected, flags):
    actual = classify([row(**values)], config, {}).rows[0]
    for key, value in expected.items():
        assert actual[key] == value
    assert all(flag in actual["inferred_flags"].split(",") for flag in flags)


def test_dso_inference_duplicates_and_unmapped(config):
    sources = [
        row("HS Leitung"),
        row("60 kV Leitung", 2),
        row("HS Leitung", 3),
        row("unmapped", 4, project_status="???"),
        row("unmapped", 5, project_status="???"),
    ]
    result = classify(sources, config, {})
    assert result.rows[0]["inferred_voltage"] == ""
    assert "duplicate_of=12-1" in result.rows[2]["inferred_flags"]
    assert result.unmapped == [
        dict(field="project_status", value="???", count=2, dso_slugs="example")
    ]
    assert result.report["dsos_without_codes"] == ["example"]
    assert result == classify(sources, config, {})


def test_document_dates_and_numeric_problems(config):
    sources = [row("UW", line_length_km="600", reported_amount_eur="0")]
    source = json.loads(sources[0]["source_cells_json"])
    source["origin"]["currentFrom"] = "2022-02"
    sources[0]["source_cells_json"] = json.dumps(source)
    result = classify(sources, config, {})
    assert "document_outside_round" in result.rows[0]["inferred_flags"]
    assert "implausible:line_length_km" in result.rows[0]["inferred_flags"]
    assert "implausible:reported_amount_eur" in result.rows[0]["inferred_flags"]


@pytest.mark.parametrize(
    ("metric", "thresholds", "expected", "expected_value"),
    [
        ("dso_count", {"pass": [1, 1], "warn": [1, 2]}, "pass", "1–1"),
        ("dso_count", {"pass": [2, 2], "warn": [1, 2]}, "warn", "2–2"),
        ("dso_count", {"pass": [3, 3], "warn": [2, 3]}, "fail", "3–3"),
        ("coverage", {"pass": 0.8, "warn": 0.5}, "fail", "≥ 0.8"),
    ],
)
def test_report_thresholds(config, metric, thresholds, expected, expected_value):
    config.validation[metric] = thresholds
    result = classify([row()], config, {})
    name = "dso_count" if metric == "dso_count" else "coverage:inferred_asset_type"
    assert (
        next(item["status"] for item in result.report["metrics"] if item["name"] == name)
        == expected
    )
    assert (
        next(item["expected"] for item in result.report["metrics"] if item["name"] == name)
        == expected_value
    )


def test_report_expectations_follow_custom_config_for_global_and_dso_metrics(config):
    config.validation["measure_share"]["pass"] = 0.97
    config.validation["vocabulary"]["pass"] = 0.98
    config.validation["coverage"]["pass"] = 0.85
    result = classify([row("Neubau 20 kV Kabel", project_status="im Bau")], config, {})
    expectations = {
        "dso_count": "80–90",
        "measure_share": "≥ 0.97",
        "vocabulary": "≥ 0.98",
        "coverage": "≥ 0.85",
        "unflagged_duplicates": "0",
        "documents_outside_round": "0",
        "unconfirmed_cleaning": "0",
    }
    for item in result.report["metrics"]:
        assert item["expected"] == expectations[item["name"].partition(":")[0]]


@pytest.mark.parametrize(
    "name",
    [
        "2022-121",
        "Erhöhung der Transformatorleistungen in Ortsnetzstationen",
        "Maßnahmen Netzstationen 2027",
        "Ortsnetzstationen Topf Ersatz",
        "Ertüchtigung einer MSP-Kabeltrasse",
    ],
)
def test_technical_text_and_codes_are_not_locations(config, name):
    assert classify([row(name)], config, {}).rows[0]["inferred_location_start"] == ""


@pytest.mark.parametrize("date_value", ["Jan 29", "2024-02-30", "2024-13", "0000"])
def test_invalid_dates_are_flagged(config, date_value):
    result = classify([row(planned_start=date_value)], config, {})
    assert "unresolved:planned_start" in result.rows[0]["inferred_flags"]
    assert result.report["unresolved_values"][0]["table"] == 12


@pytest.mark.parametrize("coverage,expected", [(1.0, "pass"), (0.5, "warn"), (0.0, "fail")])
def test_per_dso_coverage_metric_states(config, coverage, expected):
    sources = [row("Neubau 20 kV Kabel", number=1), row("2020-035", number=2)]
    if coverage == 1.0:
        sources[1] = row("Neubau 20 kV Kabel", number=2)
    elif coverage == 0:
        sources[0] = row("2020-036", number=1)
    result = classify(sources, config, {})
    for field in ["inferred_asset_type", "inferred_grid_level", "inferred_measure_type"]:
        assert (
            next(
                item["status"]
                for item in result.report["metrics"]
                if item["name"] == f"coverage:{field}"
            )
            == expected
        )


@pytest.mark.parametrize(
    "source,expected",
    [
        (row("Leitung Meißen UW", measure_description="Neubau"), "line_or_cable"),
        (row("Trafo UW X", asset_type="Schaltanlage + Trafo"), "transformer"),
        (row("Leitung UW X", asset_type="UW"), "substation"),
        (row("UW: Ausbau 110/20-kV-UW Kunrau"), "substation"),
    ],
)
def test_asset_precedence_and_station_locations(config, source, expected):
    assert classify([source], config, {}).rows[0]["inferred_asset_type"] == expected


def test_address_hyphens_and_multiple_station_tokens(config):
    sources = [
        row("Schwelm, Ernst-Adolph-Straße", asset_type="Kabel"),
        row("UW: Ausbau 110/20-kV-UW Kunrau", 2),
    ]
    result = classify(sources, config, {})
    assert result.rows[0]["inferred_location_start"] == "Schwelm, Ernst-Adolph-Straße"
    assert result.rows[0]["inferred_location_end"] == ""
    assert result.rows[1]["inferred_location_start"] == "Kunrau"


def test_categories_without_separators_are_complete_known_sequences(config):
    sources = [
        row(
            project_category=(
                "Ersatz(neubau) mit Erhöhung der Übertragungskapazität "
                "Netzoptimierung und -verstärkung"
            )
        ),
        row(project_category="Neubau/Ersatzneubau", number=2),
        row(project_category="Neubau unreadable interleaved fragment", number=3),
    ]
    result = classify(sources, config, {})
    assert result.rows[0]["inferred_project_category"] == "replacement_increase"
    assert result.rows[1]["inferred_project_category"] == "new"
    assert result.rows[2]["inferred_project_category"] == ""


def test_other_hv_voltage_in_transformer_pair_blocks_dso_default(config):
    result = classify([row("60/10 kV UW X"), row("HS Leitung", number=2)], config, {})
    assert result.rows[1]["inferred_voltage"] == ""
    assert "voltage_inferred" not in result.rows[1]["inferred_flags"]


@pytest.mark.parametrize(
    "name",
    [
        "150°C-Trassierung: Conneforde - Wiesmoor",
        "80°C-Trassierung + FLM + Umbeseilung auf ca. 0.5 km: Conneforde - Wiesmoor",
    ],
)
def test_line_technical_prefix_is_removed_before_route_splitting(config, name):
    actual = classify([row(name)], config, {}).rows[0]
    assert actual["inferred_location_start"] == "Conneforde"
    assert actual["inferred_location_end"] == "Wiesmoor"


@pytest.mark.parametrize(
    "name,types",
    [
        ("Neubau Umspannwerk X + 110 kV Anschlussleitung", "substation,line_or_cable"),
        ("Neubau UW X + 110 kV Kabel", "substation,cable"),
        ("110 kV Leitung UW X - UW Y", "line_or_cable"),
        ("Trafotausch UW Krugzell", "transformer"),
    ],
)
def test_combined_station_construction_keeps_station_but_line_endpoints_do_not(config, name, types):
    actual = classify([row(name)], config, {}).rows[0]
    assert actual["inferred_asset_types"] == types
    assert actual["inferred_asset_type"] == types.split(",")[0]


@pytest.mark.parametrize("name", ["Neubau Ortsnetzstationen", "ONS X", "Ortsnetzstation X"])
def test_local_substations_keep_voltage_independent_type(config, name):
    actual = classify([row(name)], config, {}).rows[0]
    assert actual["inferred_asset_type"] == "local_substation"
    assert actual["inferred_grid_level"] == "MV/LV"


def test_per_dso_vocabulary_conformity_exposes_weak_operator(config):
    sources = [
        row("UW A", project_status="im Bau", dso_slug="good"),
        row("UW B", number=2, project_status="???", dso_slug="weak"),
    ]
    result = classify(sources, config, {})
    metrics = {
        item["dso"]: item
        for item in result.report["metrics"]
        if item["name"] == "vocabulary:project_status"
    }
    assert metrics["good"]["value"] == 1
    assert metrics["good"]["status"] == "pass"
    assert metrics["weak"]["value"] == 0
    assert metrics["weak"]["status"] == "fail"
    assert metrics[""]["value"] == 0.5


def test_vocabulary_without_values_is_empty(config):
    config.validation["dso_count"]["pass"] = [1, 1]
    sources = [
        row("Neubau 20 kV Kabel", number=number, project_category="Neubau" if number < 4 else "")
        for number in range(1, 5)
    ]
    report = classify(sources, config, {}).report
    metrics = {(item["name"], item["dso"]): item for item in report["metrics"]}
    for dso in ["example", ""]:
        assert metrics[("vocabulary:project_category", dso)]["value"] == 1
        assert metrics[("vocabulary:project_category", dso)]["status"] == "pass"
        assert metrics[("vocabulary:primary_driver", dso)]["value"] is None
        assert metrics[("vocabulary:primary_driver", dso)]["status"] == "empty"
        assert metrics[("vocabulary:project_category", dso)]["empty_share"] == 0.25
        assert metrics[("vocabulary:primary_driver", dso)]["empty_share"] == 1
    assert "empty_share" not in metrics[("measure_share", "example")]
    assert report["status"] == "pass"
    markdown = markdown_report(report)
    assert "| vocabulary:project_category | example | 1 | 25.0% (1/4) |" in markdown
    assert "| vocabulary:primary_driver | example | - | 100.0% (4/4) |" in markdown
    assert "| measure_share | example | 1 | — |" in markdown


def test_repeated_numbers_keep_cross_table_provenance(config):
    sources = [row("UW A", measure_no="42"), row("UW B", number=2, measure_no="42")]
    provenance = json.loads(sources[1]["source_cells_json"])
    provenance["origin"].update(extract_table_id=13, document_id=8, table_number=3)
    sources[1]["source_cells_json"] = json.dumps(provenance)
    repeated = classify(sources, config, {}).report["repeated_measure_numbers"]
    assert len(repeated) == 1
    assert repeated[0]["row_ids"] == ["12-1", "13-2"]
    assert repeated[0]["sources"][1] == dict(
        row_id="13-2", document=8, extract_table_id=13, table_number=3, row_number=2
    )


def test_overview_conditions_can_be_changed_in_yaml(config):
    from nap_tool.classifier.config import ClassifyConfig

    configured = config.model_dump()
    configured["record_type"]["overview_conditions"] = [
        {"field_patterns": {"amount_kind": "^custom_total$"}}
    ]
    configured = ClassifyConfig.model_validate(configured)
    result = classify(
        [
            row("UW A", amount_kind="custom_total"),
            row("UW B", number=2, amount_kind="aggregate_total"),
        ],
        configured,
        {},
    )
    assert result.rows[0]["inferred_record_type"] == "overview"
    assert result.rows[0]["inferred_asset_type"] == ""
    assert result.rows[1]["inferred_record_type"] == "measure"
