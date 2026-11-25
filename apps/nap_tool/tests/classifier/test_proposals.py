# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Location proposals: `nap-tool propose add` and their application in `classify` (ADR-0008)."""

import csv
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from nap_tool.classifier.service import (
    CONFIG_PATH,
    OUTPUT_FILES,
    output_status,
    published_directory,
)
from nap_tool.cli import app
from nap_tool.data import sha256_file
from nap_tool.database.schema import connect

ALBBRUCK = {
    "role": "start",
    "name": "Albbruck",
    "kind": "substation",
    "evidence": {"field": "upstream_grid_node", "quote": "uw  albbruck"},
    "candidate": "node/123456",
}


@pytest.fixture
def root(repository, monkeypatch) -> Path:
    """The repository whose one record has an upstream grid node and no stage-1 location."""
    root, _, _ = repository
    monkeypatch.setenv("NAP_DATA_DIR", str(root))
    set_source(repository, upstream_grid_node="UW Albbruck")
    return root


def set_source(repository, **changes: str) -> None:
    """Rewrite the harmonized table's one record and register the new file hash."""
    root, path, values = repository
    values.update(changes)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(values))
        writer.writeheader()
        writer.writerow(values)
    with connect(root / "nap_tool.sqlite") as db:
        db.execute("UPDATE harmonize_set_output SET output_hash=?", (sha256_file(path),))


def propose(*records: dict | str) -> list[dict]:
    """Submit proposal lines through the CLI and return its report lines."""
    lines = [record if isinstance(record, str) else json.dumps(record) for record in records]
    result = CliRunner().invoke(
        app,
        [
            "propose",
            "add",
            "--set-id",
            "1",
            "--scheme-id",
            "1",
            "--model",
            "claude-test",
            "--skill-version",
            "0.1",
        ],
        input="\n".join(lines) + "\n",
    )
    assert result.exit_code == 0, result.output
    return [json.loads(line) for line in result.stdout.splitlines()]


def test_add_stores_a_valid_proposal_and_reports_it_stored(root):
    report = propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    assert report == [{"line": 1, "row_id": "1-2", "status": "stored", "proposal_id": 1}]
    with connect(root / "nap_tool.sqlite") as db:
        stored = dict(db.execute("SELECT * FROM proposal").fetchone())
        location = dict(db.execute("SELECT * FROM proposal_location").fetchone())
    assert stored["row_id"] == "1-2"
    assert (stored["model"], stored["skill_version"], stored["status"]) == (
        "claude-test",
        "0.1",
        "proposed",
    )
    assert stored["created_at"] and stored["reviewed_at"] is None
    assert location == {
        "id": 1,
        "proposal_id": 1,
        "role": "start",
        "name": "Albbruck",
        "kind": "substation",
        "evidence_field": "upstream_grid_node",
        "evidence_quote": "uw  albbruck",
        "candidate": "node/123456",
    }


def stored_proposals(root: Path) -> list[tuple[int, str]]:
    with connect(root / "nap_tool.sqlite") as db:
        return [tuple(row) for row in db.execute("SELECT id, row_id FROM proposal ORDER BY id")]


@pytest.mark.parametrize(
    "proposal,reason",
    [
        (
            {
                "row_id": "1-2",
                "locations": [{**ALBBRUCK, "evidence": {"field": "measure_name", "quote": "UW"}}],
            },
            "quote 'UW' not found in measure_name",
        ),
        ({"row_id": "9-9", "locations": [ALBBRUCK]}, "unknown row_id"),
    ],
)
def test_add_rejects_a_proposal_with_a_reason_and_stores_nothing_for_it(root, proposal, reason):
    valid = {"row_id": "1-2", "locations": [ALBBRUCK]}
    report = propose(proposal, valid)
    assert report == [
        {"line": 1, "row_id": proposal["row_id"], "status": "rejected", "reason": reason},
        {"line": 2, "row_id": "1-2", "status": "stored", "proposal_id": 1},
    ]
    assert stored_proposals(root) == [(1, "1-2")]


def test_add_rejects_a_malformed_line(root):
    [line] = propose('{"row_id": "1-2", "locations": []}')
    assert line["status"] == "rejected" and line["reason"].startswith("locations:")
    assert stored_proposals(root) == []


def stored_hash(root: Path, proposal_id: int) -> str:
    with connect(root / "nap_tool.sqlite") as db:
        return db.execute(
            "SELECT input_sha256 FROM proposal WHERE id=?", (proposal_id,)
        ).fetchone()[0]


@pytest.mark.parametrize(
    "header,value,changes",
    [
        ("Maßnahme", "Neubau 20 kV Kabel 2", True),
        ("measure_description", "Kabelneubau 2", True),
        ("upstream_grid_node", "UW Albbruck Nord", True),
        ("grid_level", "MS", False),
        ("project_category", "Neubau", False),
    ],
)
def test_input_hash_covers_only_the_reading_package_source_fields(
    repository, root, header, value, changes
):
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    set_source(repository, **{header: value})
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    assert (stored_hash(root, 1) != stored_hash(root, 2)) is changes


def classified(root: Path, *options: str) -> list[dict[str, str]]:
    """Run `nap-tool classify` and read the published classified.csv."""
    result = CliRunner().invoke(app, ["classify", "--scheme-id", "1", *options])
    assert result.exit_code in (0, 3, 4), result.output
    directory = published_directory(root / "classified/set_1", 1)
    with (directory / "classified.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_classify_fills_an_empty_start_location_from_a_proposal(root):
    [before] = classified(root)
    assert before["inferred_location_start"] == ""
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    [after] = classified(root)
    assert after["inferred_location_start"] == "Albbruck"
    assert after["inferred_location_start_kind"] == "substation"
    flags = after["inferred_flags"].split(",")
    assert "location_source:llm_proposal" in flags and "location_missing" not in flags
    assert "location_end_missing" in flags  # a line measure with a start only, as in stage 1
    assert after["inferred_quality_location"] == "medium"
    assert {key for key in before if before[key] != after[key]} == {
        "inferred_location_start",
        "inferred_location_start_kind",
        "inferred_flags",
        "inferred_quality_location",
    }


def current_csv(root: Path) -> bytes:
    return (published_directory(root / "classified/set_1", 1) / "classified.csv").read_bytes()


def test_a_proposal_that_would_replace_a_stage_1_location_is_not_applied(repository, root):
    set_source(repository, **{"Maßnahme": "Neubau 110 kV Leitung Albbruck - Waldshut"})
    [before] = classified(root)
    assert (before["inferred_location_start"], before["inferred_location_end"]) == (
        "Albbruck",
        "Waldshut",
    )
    via = {**ALBBRUCK, "role": "via", "name": "Laufenburg"}
    end = {**ALBBRUCK, "role": "end", "name": "Waldshut-Tiengen"}
    propose({"row_id": "1-2", "locations": [via, end]})
    [after] = classified(root)
    assert after == before


def test_a_stale_proposal_is_not_applied_and_leaves_the_output_unchanged(repository, root):
    set_source(repository, measure_description="Kabelneubau zum UW")
    classified(root)
    without_proposals = current_csv(root)
    set_source(repository, measure_description="Kabelneubau")
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    set_source(repository, measure_description="Kabelneubau zum UW")
    [row] = classified(root)
    assert row["inferred_location_start"] == ""
    assert current_csv(root) == without_proposals


def test_same_input_config_and_proposals_give_identical_output(root):
    classified(root)
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    assert output_status(root, 1)["stale"]
    classified(root)
    first = {
        name: (published_directory(root / "classified/set_1", 1) / name).read_bytes()
        for name in OUTPUT_FILES
    }
    classified(root)
    assert first == {
        name: (published_directory(root / "classified/set_1", 1) / name).read_bytes()
        for name in OUTPUT_FILES
    }


def test_a_classifier_rule_change_keeps_a_proposal_non_stale(root, tmp_path):
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["locations"]["generic_names"].append("Neubau 20 kV Kabel")
    path = tmp_path / "classify.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    [row] = classified(root, "--config-path", str(path))
    assert row["inferred_location_start"] == "Albbruck"


def test_a_proposal_for_a_record_of_another_set_keeps_the_output_fresh(root):
    classified(root)
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO proposal(row_id,input_sha256,model,created_at) "
            "VALUES ('9-1','x','claude-test','now')"
        )
        db.execute(
            "INSERT INTO proposal_location(proposal_id,role,name,kind,evidence_field,"
            "evidence_quote) VALUES (1,'start','Albbruck','place','measure_name','Albbruck')"
        )
    assert not output_status(root, 1)["stale"]


def rows(*options: str) -> list[dict]:
    """Run `nap-tool propose rows` and return its JSON lines."""
    result = CliRunner().invoke(
        app, ["propose", "rows", "--set-id", "1", "--scheme-id", "1", *options]
    )
    assert result.exit_code == 0, result.output
    return [json.loads(line) for line in result.stdout.splitlines()]


def test_rows_emits_a_measure_without_location_as_its_reading_package(root):
    classified(root)
    assert rows() == [
        {
            "row_id": "1-2",
            "dso_mastr_nr": "ABC",
            "asset_class": "line",
            "grid_level": "MV",
            "measure_name": "Neubau 20 kV Kabel",
            "measure_description": "Kabelneubau",
            "upstream_grid_node": "UW Albbruck",
            "location_start": "",
            "location_start_kind": "",
            "location_end": "",
            "location_end_kind": "",
            "location_via": "",
        }
    ]


@pytest.mark.parametrize(
    "name,quality,emitted",
    [
        ("Neubau 20 kV Kabel Albbruck", "medium", True),
        ("Neubau 110 kV Leitung Albbruck - Waldshut", "high", False),
        ("Diverse Kleinmaßnahmen", "not_applicable", False),
        ("Summe", "", False),
    ],
)
def test_rows_emits_only_measures_with_location_quality_none_or_medium(
    repository, root, name, quality, emitted
):
    set_source(repository, **{"Maßnahme": name})
    [row] = classified(root)
    assert row["inferred_quality_location"] == quality
    assert [package["measure_name"] for package in rows()] == ([name] if emitted else [])


@pytest.mark.parametrize(
    "description,emitted", [("", False), ("  ", False), ("Kabel nach Albbruck", True)]
)
def test_rows_skips_a_generic_name_with_an_empty_description(
    repository, root, description, emitted
):
    set_source(repository, **{"Maßnahme": "NAP  maßnahme", "measure_description": description})
    classified(root)
    assert len(rows()) == int(emitted)


def test_rows_skips_a_record_with_a_fresh_proposal_until_its_source_text_changes(repository, root):
    classified(root)
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    assert rows() == []
    with connect(root / "nap_tool.sqlite") as db:
        db.execute("UPDATE proposal SET status='rejected'")
    assert rows() == []
    set_source(repository, measure_description="Kabelneubau zum UW")
    classified(root)
    assert [package["row_id"] for package in rows()] == ["1-2"]


def set_records(repository, records: list[dict[str, str]]) -> None:
    """Rewrite the harmonized table with several records and register its new hash."""
    root, path, values = repository
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(values))
        writer.writeheader()
        writer.writerows(records)
    with connect(root / "nap_tool.sqlite") as db:
        db.execute("UPDATE harmonize_set_output SET output_hash=?", (sha256_file(path),))


def test_rows_filters_by_dso_and_limits_the_count(repository, root):
    values = repository[2]
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO dso(name,slug,mastr_nr,bdew_code,created_at,updated_at) "
            "VALUES ('Other','other','XYZ','456','now','now')"
        )
    cells = json.loads(values["source_cells_json"])
    records = []
    for number, slug in [(2, "test"), (3, "other"), (4, "test")]:
        cells["origin"]["row_number"] = number
        records.append({**values, "dso_slug": slug, "source_cells_json": json.dumps(cells)})
    set_records(repository, records)
    classified(root)
    assert [package["row_id"] for package in rows()] == ["1-2", "1-3", "1-4"]
    assert [package["row_id"] for package in rows("--dso", "ABC")] == ["1-2", "1-4"]
    assert [package["row_id"] for package in rows("--limit", "2")] == ["1-2", "1-3"]
    assert [package["row_id"] for package in rows("--dso", "ABC", "--limit", "1")] == ["1-2"]


def test_rows_without_classification_output_fails_with_a_clear_error(root):
    result = CliRunner().invoke(app, ["propose", "rows", "--set-id", "1", "--scheme-id", "1"])
    assert result.exit_code == 1
    assert "No classification output for set 1 and scheme 1; run classify first" in result.stderr


def test_rows_reads_the_current_source_text_like_propose_add(repository, root):
    classified(root)
    set_source(repository, measure_description="Kabel zum UW Albbruck")
    [package] = rows()
    assert package["measure_description"] == "Kabel zum UW Albbruck"
    propose({"row_id": "1-2", "locations": [ALBBRUCK]})
    assert rows() == []
