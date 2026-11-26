# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Proposal review: `nap-tool propose review export/import` and its effect on `classify`."""

import csv
import json
from collections import Counter
from pathlib import Path

import pytest
from test_proposals import ALBBRUCK, classified, propose, set_source
from typer.testing import CliRunner

from nap_tool.cli import app
from nap_tool.data import sha256_file
from nap_tool.database.schema import connect

VIA = {**ALBBRUCK, "role": "via", "name": "Laufenburg"}
END = {**ALBBRUCK, "role": "end", "name": "Waldshut-Tiengen", "candidate": None}


@pytest.fixture
def root(repository, monkeypatch) -> Path:
    """The repository whose one record is a line with stage-1 start and end locations."""
    root, _, _ = repository
    monkeypatch.setenv("NAP_DATA_DIR", str(root))
    set_source(
        repository,
        upstream_grid_node="UW Albbruck",
        **{"Maßnahme": "Neubau 110 kV Leitung Albbruck - Waldshut"},
    )
    return root


def export(root: Path) -> list[dict[str, str]]:
    """Run `nap-tool propose review export` and read the written CSV."""
    path = root / "review.csv"
    result = CliRunner().invoke(
        app,
        ["propose", "review", "export", str(path), "--set-id", "1", "--scheme-id", "1"],
    )
    assert result.exit_code == 0, result.output
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_export_lists_a_conflicting_proposal_with_an_empty_decision(root):
    propose({"row_id": "1-2", "locations": [VIA, END]})
    assert export(root) == [
        {
            "proposal_id": "1",
            "row_id": "1-2",
            "reason": "conflict",
            "measure_name": "Neubau 110 kV Leitung Albbruck - Waldshut",
            "measure_description": "Kabelneubau",
            "upstream_grid_node": "UW Albbruck",
            "stage1_location": "start: Albbruck; end: Waldshut",
            "proposal": "via: Laufenburg (substation); end: Waldshut-Tiengen (substation)",
            "candidate": "node/123456; ",
            "decision": "",
        }
    ]


def write_records(repository, dso_counts: dict[str, int]) -> list[str]:
    """Replace the harmonized table with unlocated records per DSO; return their row ids."""
    root, path, values = repository
    rows = []
    for dso, count in dso_counts.items():
        for _ in range(count):
            origin = {"extract_table_id": 1, "row_number": len(rows) + 2}
            rows.append(
                {
                    **values,
                    "dso_slug": dso,
                    "Maßnahme": "Neubau 20 kV Kabel",
                    "upstream_grid_node": "UW Albbruck",
                    "source_cells_json": json.dumps({"origin": origin, "sources": []}),
                }
            )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(values))
        writer.writeheader()
        writer.writerows(rows)
    with connect(root / "nap_tool.sqlite") as db:
        db.execute("UPDATE harmonize_set_output SET output_hash=?", (sha256_file(path),))
    return [f"1-{number}" for number in range(2, len(rows) + 2)]


def test_export_samples_auto_accepted_proposals_per_dso_and_kind_reproducibly(repository, root):
    row_ids = write_records(repository, {"a": 100, "b": 10, "c": 2})
    kinds = ["substation"] * 60 + ["place"] * 25 + ["local_substation"] * 15 + ["substation"] * 12
    propose(
        *(
            {"row_id": row, "locations": [{**ALBBRUCK, "kind": kind}]}
            for row, kind in zip(row_ids, kinds)
        )
    )
    sample = export(root)
    assert {row["reason"] for row in sample} == {"audit"}
    dso_of = {row: dso for row, dso in zip(row_ids, ["a"] * 100 + ["b"] * 10 + ["c"] * 2)}
    strata = Counter(
        (dso_of[row["row_id"]], row["proposal"].split("(")[1].rstrip(")")) for row in sample
    )
    # About 5 % per DSO, at least 3, split over the kinds in proportion (largest remainder).
    assert strata == {
        ("a", "substation"): 3,
        ("a", "place"): 1,
        ("a", "local_substation"): 1,
        ("b", "substation"): 3,
        ("c", "substation"): 2,
    }
    assert export(root) == sample


def review(root: Path, rows: list[dict[str, str]], **decisions: str):
    """Write decisions by proposal id into the review CSV and import it."""
    path = root / "review.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(
            {**row, "decision": decisions.get(f"p{row['proposal_id']}", "")} for row in rows
        )
    return CliRunner().invoke(app, ["propose", "review", "import", str(path)])


def stored(root: Path) -> list[dict]:
    with connect(root / "nap_tool.sqlite") as db:
        return [dict(row) for row in db.execute("SELECT * FROM proposal ORDER BY id")]


def test_an_accepted_conflicting_proposal_replaces_the_stage_1_location(root):
    propose({"row_id": "1-2", "locations": [VIA, END]})
    result = review(root, export(root), p1="accept")
    assert result.exit_code == 0, result.output
    [proposal] = stored(root)
    assert proposal["status"] == "accepted" and proposal["reviewed_at"]
    [row] = classified(root)
    assert (
        row["inferred_location_start"],
        row["inferred_location_via"],
        row["inferred_location_end"],
        row["inferred_location_end_kind"],
    ) == ("Albbruck", "Laufenburg", "Waldshut-Tiengen", "substation")
    flags = row["inferred_flags"].split(",")
    assert {"location_source:llm_proposal", "llm_proposal_reviewed"} <= set(flags)
    assert "llm_proposal_conflict" not in flags
    assert row["inferred_quality_location"] == "high"


def test_a_rejected_proposal_is_never_applied_and_stays_in_the_database(root):
    [before] = classified(root)
    propose({"row_id": "1-2", "locations": [VIA, END]})
    assert review(root, export(root), p1="reject").exit_code == 0
    [after] = classified(root)
    assert after == before
    assert [proposal["status"] for proposal in stored(root)] == ["rejected"]
    assert export(root) == []


def test_a_correction_stores_an_accepted_human_proposal_that_classify_applies(root):
    propose({"row_id": "1-2", "locations": [VIA, END]})
    result = review(root, export(root), p1="Laufenburg; Waldshut")
    assert result.exit_code == 0, result.output
    original, corrected = stored(root)
    assert (original["status"], original["reviewed_at"]) == ("rejected", corrected["reviewed_at"])
    assert (corrected["model"], corrected["skill_version"], corrected["status"]) == (
        "human",
        None,
        "accepted",
    )
    assert corrected["input_sha256"] == original["input_sha256"]
    with connect(root / "nap_tool.sqlite") as db:
        locations = [
            (row["role"], row["name"], row["candidate"])
            for row in db.execute("SELECT * FROM proposal_location WHERE proposal_id=2")
        ]
    assert locations == [("via", "Laufenburg", "node/123456"), ("end", "Waldshut", None)]
    [row] = classified(root)
    assert (row["inferred_location_via"], row["inferred_location_end"]) == (
        "Laufenburg",
        "Waldshut",
    )


@pytest.mark.parametrize(
    "decisions,message",
    [
        ({"p1": "accept", "p9": "reject"}, "unknown proposal id '9'"),
        ({"p1": "accept", "p2": "only one name"}, "invalid decision 'only one name'"),
    ],
)
def test_import_refuses_an_unknown_id_or_invalid_decision_and_writes_nothing(
    repository, root, decisions, message
):
    propose({"row_id": "1-2", "locations": [VIA, END]})
    rows = export(root)
    set_source(repository, measure_description="Kabelneubau Albbruck")
    propose({"row_id": "1-2", "locations": [VIA, END]})
    rows += [{**rows[0], "proposal_id": "2"}, {**rows[0], "proposal_id": "9"}]
    before = stored(root)
    result = review(root, rows, **decisions)
    assert result.exit_code == 1
    assert message in result.output
    assert stored(root) == before


def test_an_accepted_proposal_for_some_locations_keeps_the_stage_1_flags_of_the_others(root):
    [before] = classified(root)
    assert "location_source:measure_name" in before["inferred_flags"].split(",")
    propose({"row_id": "1-2", "locations": [END]})
    assert review(root, export(root), p1="accept").exit_code == 0
    [row] = classified(root)
    assert (row["inferred_location_start"], row["inferred_location_end"]) == (
        "Albbruck",
        "Waldshut-Tiengen",
    )
    assert "location_source:measure_name" in row["inferred_flags"].split(",")


def test_a_conflicting_proposal_does_not_block_a_gap_filling_one_of_the_same_record(
    repository, root
):
    set_source(
        repository,
        measure_description="Kabel von Dogern nach Waldshut",
        **{"Maßnahme": "Neubau 20 kV Kabel Albbruck"},
    )
    end = {
        **END,
        "name": "Waldshut",
        "evidence": {"field": "measure_description", "quote": "Waldshut"},
    }
    start = {
        **end,
        "role": "start",
        "name": "Dogern",
        "evidence": {**end["evidence"], "quote": "Dogern"},
    }
    propose({"row_id": "1-2", "locations": [end]}, {"row_id": "1-2", "locations": [start, end]})
    [row] = classified(root)
    assert (row["inferred_location_start"], row["inferred_location_end"]) == (
        "Albbruck",
        "Waldshut",
    )
    flags = row["inferred_flags"].split(",")
    assert {"location_source:llm_proposal", "llm_proposal_conflict"} <= set(flags)
    rows = export(root)
    assert [(item["proposal_id"], item["reason"]) for item in rows] == [
        ("2", "conflict"),
        ("1", "audit"),
    ]
    assert review(root, rows[:1], p2="accept").exit_code == 0
    [row] = classified(root)
    assert (row["inferred_location_start"], row["inferred_location_end"]) == ("Dogern", "Waldshut")
    assert "llm_proposal_conflict" not in row["inferred_flags"].split(",")


def test_an_accepted_correction_repeating_stage_1_does_not_block_a_gap_filling_proposal(root):
    propose({"row_id": "1-2", "locations": [END]})
    assert review(root, export(root), p1="waldshut").exit_code == 0
    propose({"row_id": "1-2", "locations": [VIA]})
    [row] = classified(root)
    assert (row["inferred_location_end"], row["inferred_location_via"]) == (
        "Waldshut",
        "Laufenburg",
    )
