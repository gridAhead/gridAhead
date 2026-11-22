# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Compact sheet marking, reading and comparison."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from nap_tool.classifier.compact_sheet import (
    CompactSheet,
    compare,
    read_compact_sheet,
    record_totals,
)
from nap_tool.database.schema import connect
from nap_tool.ui.server import create_app

SETTINGS = {"pass": 0.01, "warn": 0.10, "cost_divisor": 1_000_000}
GROUPS = [
    "Neubau",
    "Ersatz(neubau) mit Erhöhung der Übertragungskapazität; Netzoptimierung und -verstärkung",
    "Reiner Ersatz (1:1) / Rückbau / Altlastentsorgung",
]


def build_sheet(path: Path, hv_km: float = 10.0, *, names=("Nord",), title=None) -> Path:
    """A template workbook with HV (km, cost) and HV/MV (count, MVA, cost) blocks."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datenblatt vnbdigital.de"
    ws["B1"] = title or "Erwarteter Netzausbaubedarf bis 2045 gemäß NAP 2026"
    ws["B2"] = "Summe netzdimensionierend"  # precomputed totals are ignored
    ws["E11"], ws["H11"] = "Hochspannung", "Hoch- auf Mittelspannung"
    ws["B15"] = "Projektkategorie"
    ws["E15"], ws["H15"] = "2025 bis 2030 (T+5)", "2025 bis 2030 (T+5)"
    ws["E16"], ws["F16"] = "Kilometer", "geschätzter Bedarf"
    ws["H16"], ws["I16"], ws["J16"] = "Anzahl", "MVA", "geschätzter Bedarf"
    row = 17
    for name in (*names, "Teilnetzgebiet nicht benannt"):
        for index, group in enumerate(GROUPS):
            if index == 0:
                ws.cell(row, 1, name)
            ws.cell(row, 2, group)
            if name != "Teilnetzgebiet nicht benannt":
                ws.cell(row, 5, hv_km if index == 0 else 0)
                ws.cell(row, 6, 2.0 if index == 0 else 0)
                ws.cell(row, 8, 3 if index == 0 else None)
                ws.cell(row, 9, 40 if index == 0 else 0)
                ws.cell(row, 10, 1.0 if index == 0 else 0)
            row += 1
    wb.save(path)
    return path


def record(slug, category, level, **extra):
    source = {"dso_slug": slug, "planning_horizon": "T+5", "subgrid_area": "Nord", **extra}
    out = {
        "inferred_record_type": "measure",
        "inferred_flags": "",
        "inferred_grid_level": level,
        "inferred_project_category": category,
        "inferred_asset_class": "line" if level in {"HV", "MV", "LV"} else "station",
    }
    return out, source


def run(sheet, records, dsos=("a",)):
    rows, inputs = zip(*records) if records else ([], [])
    totals = record_totals(list(rows), list(inputs), SETTINGS)
    return compare({"a": sheet} if sheet else {}, totals, list(dsos), SETTINGS)


def test_reads_subgrid_cells_and_ignores_unnamed_template_rows(tmp_path: Path) -> None:
    sheet = read_compact_sheet(build_sheet(tmp_path / "s.xlsx"), 7)
    assert not sheet.error
    assert list(sheet.subgrids) == ["Nord"]
    cells = sheet.subgrids["Nord"]
    assert cells[("HV", "T+5", "new", "km")] == 10
    assert cells[("HV", "T+5", "new", "cost")] == 2
    assert cells[("HV/MV", "T+5", "new", "count")] == 3
    assert cells[("HV/MV", "T+5", "increase", "count")] is None  # empty cell = missing
    assert cells[("HV", "T+5", "increase", "km")] == 0  # explicit 0 = no need


def test_unexpected_layout_fails_without_parsing(tmp_path: Path) -> None:
    bad = read_compact_sheet(build_sheet(tmp_path / "s.xlsx", title="Etwas anderes"))
    assert "unexpected layout" in bad.error and not bad.subgrids
    path = build_sheet(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(path)
    wb.active["F16"] = "Tonnen"
    wb.save(path)
    assert "unexpected layout" in read_compact_sheet(path).error


def test_matching_records_pass_and_deviations_are_listed(tmp_path: Path) -> None:
    sheet = read_compact_sheet(build_sheet(tmp_path / "s.xlsx"))
    good = [
        record("a", "new", "HV", line_length_km="10", reported_amount_eur="2000000"),
        record("a", "new", "HV/MV", capacity_change_mva="40", reported_amount_eur="1000000"),
    ]
    good += [record("a", "new", "HV/MV")] * 2  # station count 3 in total
    result = run(sheet, good)
    assert [m["status"] for m in result["metrics"]] == ["pass"]
    assert result["deviations"] == []

    off = [record("a", "new", "HV", line_length_km="10.5", reported_amount_eur="2000000")]
    result = run(sheet, off)
    km = [d for d in result["deviations"] if d["quantity"] == "km"]
    assert {d["subgrid_area"] for d in km} == {"Nord", "(total)"}
    assert km[0]["status"] == "warn" and km[0]["deviation_percent"] == 5.0
    # Nonzero sum against an explicit 0 fails; the hand-filled count is at worst warn.
    zero = [record("a", "replacement_no_increase", "HV", line_length_km="1")]
    assert run(sheet, zero)["metrics"][0]["status"] == "fail"
    counts = [d for d in run(sheet, off)["deviations"] if d["quantity"] == "count"]
    assert counts and {d["status"] for d in counts} == {"warn"}


def test_quantity_no_record_carries_is_not_compared(tmp_path: Path) -> None:
    sheet = read_compact_sheet(build_sheet(tmp_path / "s.xlsx"))
    # km is filled (and matches), cost and MVA are missing from every record.
    result = run(sheet, [record("a", "new", "HV", line_length_km="10")])
    assert {d["quantity"] for d in result["deviations"]} <= {"count"}
    assert result["metrics"][0]["status"] in {"pass", "warn"}
    # Nothing fillable at all: not comparable, neither pass nor fail.
    nothing = run(sheet, [record("a", "new", "HV")])
    assert nothing["deviations"] == [] or {d["quantity"] for d in nothing["deviations"]} == {
        "count"
    }


def test_cell_without_records_is_a_coverage_gap_not_a_deviation(tmp_path: Path) -> None:
    sheet = read_compact_sheet(build_sheet(tmp_path / "s.xlsx"))
    # The sheet states 10 km, but the only record is in another category group.
    other = record("a", "replacement_no_increase", "HV", line_length_km="0")
    result = run(sheet, [other])
    km = [d for d in result["deviations"] if d["quantity"] == "km"]
    assert km == []
    assert result["metrics"][0]["uncovered_cells"] > 0
    # A record that contributes to the cell but differs is still a deviation.
    result = run(sheet, [record("a", "new", "HV", line_length_km="20")])
    assert [d["status"] for d in result["deviations"] if d["quantity"] == "km"] == ["fail"] * 2


def test_dso_without_sheet_is_empty_and_errors_fail(tmp_path: Path) -> None:
    assert run(None, [record("a", "new", "HV")])["metrics"][0]["status"] == "empty"
    broken = CompactSheet(3, "unexpected layout: x")
    assert run(broken, [])["metrics"][0]["status"] == "fail"


def test_subgrid_matching_and_unassigned_horizons(tmp_path: Path) -> None:
    sheet = read_compact_sheet(build_sheet(tmp_path / "s.xlsx"))
    records = [
        record("a", "new", "HV", line_length_km="10", subgrid_area="  NORD "),
        record("a", "new", "HV", line_length_km="1", subgrid_area="Elsewhere"),
        record("a", "new", "HV", line_length_km="1", planning_horizon="2030"),
    ]
    duplicate = record("a", "new", "HV", line_length_km="100")
    duplicate[0]["inferred_flags"] = "duplicate_of=1-1"
    result = run(sheet, [*records, duplicate])
    assert result["unmatched_subgrid_areas"] == [
        dict(dso="a", side="records", subgrid_area="Elsewhere")
    ]
    assert result["unassigned_planning_horizons"] == [dict(dso="a", count=1)]
    # "Nord" matches after strip + casefold, the unmatched area counts toward the total only.
    km = [d for d in result["deviations"] if d["quantity"] == "km"]
    assert [d["subgrid_area"] for d in km] == ["(total)"]
    assert km[0]["actual"] == 11


def test_records_without_subgrid_go_to_the_only_named_area(tmp_path: Path) -> None:
    one = read_compact_sheet(build_sheet(tmp_path / "s.xlsx"))
    rec = record("a", "new", "HV", line_length_km="10", subgrid_area="")
    assert not [d for d in run(one, [rec])["deviations"] if d["quantity"] == "km"]
    two = read_compact_sheet(build_sheet(tmp_path / "t.xlsx", names=("Nord", "Süd")))
    result = run(two, [rec])
    assert not [d for d in result["deviations"] if d["subgrid_area"] == "Nord"]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'A', 'a', '2026-01-01', '2026-01-01')"
        )
        for number, (path, year) in enumerate(
            [
                ("documents/a/1.xlsx", 2026),
                ("documents/a/2.xlsx", 2026),
                ("documents/a/3.pdf", 2026),
                ("documents/a/4.xlsx", None),
            ],
            start=1,
        ):
            connection.execute(
                "INSERT INTO document(id, dso_id, title, hash, source, file_path, nap_year, "
                "created_at, updated_at) VALUES (?, 1, 't', ?, 'custom', ?, ?, 'x', 'x')",
                (number, str(number) * 64, path, year),
            )
    return TestClient(create_app(tmp_path))


def mark(client: TestClient, document: int, value: bool = True):
    updated = next(d for d in client.get("/api/overview/documents").json() if d["id"] == document)
    return client.patch(
        f"/api/overview/documents/{document}/compact-sheet",
        json={"is_compact_sheet": value, "expected_updated_at": updated["updated_at"]},
    )


def test_marking_replaces_the_previous_sheet_of_the_round(client: TestClient) -> None:
    assert mark(client, 1).status_code == 200
    assert mark(client, 2).status_code == 200
    flags = {d["id"]: d["is_compact_sheet"] for d in client.get("/api/overview/documents").json()}
    assert flags == {1: 0, 2: 1, 3: 0, 4: 0}
    assert mark(client, 2, False).status_code == 200


def test_only_xlsx_documents_with_a_round_can_be_marked(client: TestClient) -> None:
    assert mark(client, 3).status_code == 422
    assert mark(client, 4).status_code == 422
    assert (
        client.patch(
            "/api/overview/documents/1/compact-sheet",
            json={"is_compact_sheet": True, "expected_updated_at": "stale"},
        ).status_code
        == 409
    )


def test_service_reads_the_marked_sheet_of_the_config_round(tmp_path: Path) -> None:
    import sqlite3

    from nap_tool.classifier.config import CONFIG_PATH
    from nap_tool.classifier.service import _compact_sheets
    from nap_tool.data import sha256_file

    (tmp_path / "documents").mkdir()
    workbook = build_sheet(tmp_path / "documents" / "a.xlsx")
    digest = sha256_file(workbook)
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) VALUES (1,'A','a','x','x')"
        )
        # Marked in 2026, marked in another round, and an unmarked 2026 document.
        for number, (year, marked, file_hash) in enumerate(
            [(2026, 1, digest), (2024, 1, "b" * 64), (2026, 0, "c" * 64)], start=1
        ):
            connection.execute(
                "INSERT INTO document(id, dso_id, title, hash, source, file_path, nap_year, "
                "is_compact_sheet, created_at, updated_at) "
                "VALUES (?, 1, 't', ?, 'custom', 'documents/a.xlsx', ?, ?, 'x', 'x')",
                (number, file_hash, year, marked),
            )
        connection.row_factory = sqlite3.Row
        sheets = _compact_sheets(connection, tmp_path, CONFIG_PATH.with_name("classify_2026.yaml"))
    assert list(sheets) == ["a"]
    assert sheets["a"].document_id == 1 and not sheets["a"].error
