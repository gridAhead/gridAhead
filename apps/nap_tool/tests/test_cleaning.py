# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic cleaning rules and versioned review API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nap_tool.cleaning import (
    CleanConfig,
    ColumnRule,
    clean_grid,
    csv_bytes,
    default_config,
    load_cleaning_globals,
    with_tool_number_format,
)
from nap_tool.data import write_bytes
from nap_tool.database.schema import connect
from nap_tool.ui.server import create_app


def test_clean_grid_converts_values_and_preserves_unresolved() -> None:
    """Units, dates, placeholders, and unresolved input remain traceable."""
    globals_config = load_cleaning_globals(Path(__file__).parents[1] / "config/cleaning.yaml")
    rows = [
        ["Kosten [Mio. €]", "Datum", "Leistung [MVA]", "Status"],
        ["1,6", "Jan 24", "100 kVA", "Vorgesehene Maßnahmen"],
        ["-", "2024-2028", "141 MW", "unbekannt"],
    ]
    config = CleanConfig(
        columns=[
            ColumnRule(index=0, kind="money", source_unit="Mio. €"),
            ColumnRule(index=1, kind="date"),
            ColumnRule(index=2, kind="number", source_unit="MVA", target_unit="MVA"),
            ColumnRule(
                index=3, kind="choice", choices={"vorgesehene Maßnahme": ["Vorgesehene Maßnahmen"]}
            ),
        ]
    )
    cleaned, cells = clean_grid(rows, config, globals_config)
    assert cleaned[1] == ["1600000", "2024-01", "0.1", "vorgesehene Maßnahme"]
    assert cleaned[2] == ["", "2024-2028", "141 MW", "unbekannt"]
    unresolved = {(cell["row"], cell["column"]) for cell in cells if cell["status"] == "unresolved"}
    assert unresolved == {(2, 1), (2, 2), (2, 3)}


def test_default_number_rule_uses_header_unit() -> None:
    """A column's declared MVA unit remains the target for explicit kVA cells."""
    globals_config = load_cleaning_globals(Path(__file__).parents[1] / "config/cleaning.yaml")
    config = default_config(["Änderung [+/- MVA]"])
    assert config.columns[0].kind == "number"
    assert config.columns[0].source_unit == "MVA"
    cleaned, _ = clean_grid([["Änderung [+/- MVA]"], ["100 kVA"]], config, globals_config)
    assert cleaned[1][0] == "0.1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.102", "0.102"), ("6.443", "6.443"), ("1126", "1126"), ("2,85", "2.85"), ("-0.5", "-0.5")],
)
def test_spreadsheet_numbers_use_machine_format(value: str, expected: str) -> None:
    """XLSX cells hold repr(float): 0.102 km is not the thousands group 102."""
    globals_config = load_cleaning_globals(Path(__file__).parents[1] / "config/cleaning.yaml")
    header = "Länge [km]"
    config = default_config([header], tool="xlsx")
    assert (config.decimal_separator, config.thousands_separator) == (".", "")
    cleaned, _ = clean_grid([[header], [value]], config, globals_config)
    assert cleaned[1][0] == expected


def test_pdf_tables_keep_german_number_format() -> None:
    """Text tables keep the German default, where 1.126 is a thousands group."""
    globals_config = load_cleaning_globals(Path(__file__).parents[1] / "config/cleaning.yaml")
    config = default_config(["Länge [km]"], tool="llmPDF")
    cleaned, _ = clean_grid([["Länge [km]"], ["1.126"], ["0,5"]], config, globals_config)
    assert [row[0] for row in cleaned[1:]] == ["1126", "0.5"]


def test_reviewer_number_format_is_kept_for_spreadsheets() -> None:
    """Only the untouched default format is replaced for spreadsheet tables."""
    legacy = CleanConfig()
    assert with_tool_number_format(legacy, "xlsx").thousands_separator == ""
    assert with_tool_number_format(legacy, "docling") == legacy
    chosen = CleanConfig(decimal_separator=",", thousands_separator=" ")
    assert with_tool_number_format(chosen, "xlsx") == chosen


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-12-31 01:00:00", "2026-12-31"),
        ("2025-07-10T02:00", "2025-07-10"),
        ("2027-01-01", "2027-01-01"),
        ("2028-12", "2028-12"),
        ("12/2028", "2028-12"),
    ],
)
def test_iso_dates_and_spreadsheet_datetimes_become_days(value: str, expected: str) -> None:
    """Spreadsheet datetimes with time-zone artefacts keep only the day."""
    globals_config = load_cleaning_globals(Path(__file__).parents[1] / "config/cleaning.yaml")
    config = CleanConfig(columns=[ColumnRule(index=0, kind="date")])
    cleaned, cells = clean_grid([["Inbetriebnahme"], [value]], config, globals_config)
    assert cleaned[1][0] == expected
    assert not [cell for cell in cells if cell["status"] == "unresolved"]


def test_selected_header_row_preserves_preamble_and_cleans_only_data() -> None:
    """Rows before and including a selected header stay unchanged."""
    globals_config = load_cleaning_globals(Path(__file__).parents[1] / "config/cleaning.yaml")
    rows = [
        ["Erläuterung", "Fassung"],
        ["Kosten [Mio. €]", "Status"],
        ["1,6", "open"],
    ]
    config = default_config(rows[1], header_row=2)
    cleaned, cells = clean_grid(rows, config, globals_config)
    assert cleaned[:2] == rows[:2]
    assert cleaned[2] == ["1600000", "open"]
    assert {(cell["row"], cell["column"]) for cell in cells} == {(2, 0)}


def test_clean_version_review_and_source_fallback(tmp_path: Path) -> None:
    """A version copies reviewed extraction, saves edits, and flags later rule changes."""
    source = csv_bytes([["Kosten [Mio. €]", "Status"], ["1,6", "open"]])
    source_hash = write_bytes(tmp_path, "extracted/source.csv", source)
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'Provider', 'provider', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO document(id, dso_id, title, source, created_at, updated_at) "
            "VALUES (1, 1, 'NAP', 'test', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO extract_table(id, document_id, tool, table_number, "
            "extract_table_hash, extract_table_path, extract_created_at) "
            "VALUES (1, 1, 'docling', 1, ?, 'extracted/source.csv', '2026-01-01')",
            (source_hash,),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
    client = TestClient(create_app(tmp_path))
    created = client.post("/api/clean-versions", json={"extract_id": 1}).json()
    clean_id = created["id"]
    first = client.get(f"/api/clean-review/{clean_id}").json()
    assert first["source_rows"] == [["Kosten [Mio. €]", "Status"], ["1,6", "open"]]
    assert first["automatic_rows"][1][0] == "1600000"
    assert first["reviewed_rows"] is None
    assert first["rows"] == first["automatic_rows"]
    edited = [list(row) for row in first["rows"]]
    edited[1][1] = "approved"
    saved = client.put(
        f"/api/clean-review/{clean_id}",
        json={
            "rows": edited,
            "expected_clean_hash": first["clean_hash"],
            "expected_reviewed_hash": None,
            "confirm": True,
        },
    )
    assert saved.status_code == 200
    assert client.get(f"/api/clean-review/{clean_id}").json()["reviewed_rows"][1][1] == "approved"
    metadata_url = f"/api/clean-review/{clean_id}/metadata"
    assert client.patch(metadata_url, json={"title": "Prüffassung"}).status_code == 200
    assert client.patch(metadata_url, json={"note": "Geprüft"}).status_code == 200
    assert client.get(f"/api/clean-review/{clean_id}").json()["note"] == "Geprüft"
    config = first["config"]
    assert config["columns"][1]["configured"] is False
    config["columns"][0]["kind"] = "text"
    config["columns"][0]["configured"] = True
    changed = client.put(
        f"/api/clean-review/{clean_id}/rules",
        json={
            "config": config,
            "expected_clean_hash": first["clean_hash"],
            "expected_source_hash": first["source_hash"],
        },
    )
    assert changed.status_code == 200
    reread = client.get(f"/api/clean-review/{clean_id}").json()
    assert reread["config"]["columns"][0]["configured"] is True
    assert reread["automatic_rows"][1][0] == "1,6"
    assert reread["reviewed_rows"][1][0] == "1,6"
    assert reread["reviewed_rows"][1][1] == "approved"
    assert reread["review_is_stale"] is True
    assert reread["is_confirmed"] is False
    assert (
        client.put(
            f"/api/clean-review/{clean_id}/rules",
            json={
                "config": config,
                "expected_clean_hash": first["clean_hash"],
                "expected_source_hash": first["source_hash"],
            },
        ).status_code
        == 409
    )

    without_rule = {
        **reread["config"],
        "columns": [column for column in reread["config"]["columns"] if column["index"] != 0],
    }
    removed = client.put(
        f"/api/clean-review/{clean_id}/rules",
        json={
            "config": without_rule,
            "expected_clean_hash": reread["clean_hash"],
            "expected_source_hash": reread["source_hash"],
        },
    )
    assert removed.status_code == 200
    after_removal = client.get(f"/api/clean-review/{clean_id}").json()
    assert all(column["index"] != 0 for column in after_removal["config"]["columns"])
    assert after_removal["automatic_rows"][1][0] == "1,6"

    reviewed = csv_bytes([["Kosten [Mio. €]", "Status"], ["2,0", "open"]])
    reviewed_hash = write_bytes(tmp_path, "extract_reviewed/review.csv", reviewed)
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "UPDATE extract_table SET extract_reviewed_table_hash=?, "
            "extract_reviewed_table_path=? WHERE id=1",
            (reviewed_hash, "extract_reviewed/review.csv"),
        )
    second = client.post("/api/clean-versions", json={"extract_id": 1}).json()
    second_review = client.get(f"/api/clean-review/{second['id']}").json()
    assert second_review["source_rows"][1][0] == "2,0"
    assert second_review["automatic_rows"][1][0] == "2,0"
    assert client.get(f"/api/clean-review/{clean_id}").json()["is_stale"] is True
    assert second_review["is_selected"] is True
    assert client.patch(metadata_url, json={"is_selected": True}).status_code == 200
    assert client.get(f"/api/clean-review/{clean_id}").json()["is_selected"] is True
    assert client.get(f"/api/clean-review/{second['id']}").json()["is_selected"] is False

    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO harmonize_scheme(id,name,created_at,updated_at) "
            "VALUES (1,'Test','now','now')"
        )
        database.execute(
            "INSERT INTO harmonize_field(scheme_id,title,created_at,updated_at) "
            "VALUES (1,'Status','now','now')"
        )
        database.execute(
            "INSERT INTO harmonize_field_source(field_id,position,extract_id,column_index,"
            "header,mode,stage,clean_id) VALUES (last_insert_rowid(),0,1,0,'Status',"
            "'fixed','clean_table',?)",
            (clean_id,),
        )
    delete_url = f"/api/clean-versions/{clean_id}"
    assert client.delete(delete_url).status_code == 409
    assert client.get(f"/api/clean-review/{clean_id}").status_code == 200
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute("DELETE FROM harmonize_field WHERE scheme_id=1")
    assert client.delete(delete_url).json() == {"selected_id": second["id"]}
    assert client.get(f"/api/clean-review/{second['id']}").json()["is_selected"] is True
    assert client.delete(delete_url).status_code == 404
    assert client.delete(f"/api/clean-versions/{second['id']}").json() == {"selected_id": None}


def test_changing_header_row_recomputes_and_preserves_manual_edits(tmp_path: Path) -> None:
    """A new header row refreshes automatic suggestions and leaves review edits pending."""
    source = csv_bytes([["Erläuterung", "Fassung"], ["Kosten [Mio. €]", "Status"], ["1,6", "open"]])
    source_hash = write_bytes(tmp_path, "extracted/source.csv", source)
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'Provider', 'provider', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO document(id, dso_id, title, source, created_at, updated_at) "
            "VALUES (1, 1, 'NAP', 'test', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO extract_table(id, document_id, tool, table_number, "
            "extract_table_hash, extract_table_path, "
            "extract_created_at) "
            "VALUES (1, 1, 'docling', 1, ?, 'extracted/source.csv', '2026-01-01')",
            (source_hash,),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
    client = TestClient(create_app(tmp_path))
    clean_id = client.post("/api/clean-versions", json={"extract_id": 1}).json()["id"]
    first = client.get(f"/api/clean-review/{clean_id}").json()
    edited = [list(row) for row in first["rows"]]
    edited[2][1] = "approved"
    assert (
        client.put(
            f"/api/clean-review/{clean_id}",
            json={
                "rows": edited,
                "expected_clean_hash": first["clean_hash"],
                "expected_reviewed_hash": None,
                "confirm": True,
            },
        ).status_code
        == 200
    )

    config = {**first["config"], "header_row": 2}
    config["columns"][1]["configured"] = True
    changed = client.put(
        f"/api/clean-review/{clean_id}/rules",
        json={
            "config": config,
            "expected_clean_hash": first["clean_hash"],
            "expected_source_hash": source_hash,
        },
    )
    assert changed.status_code == 200
    updated = client.get(f"/api/clean-review/{clean_id}").json()
    assert updated["config"]["header_row"] == 2
    assert updated["config"]["columns"][0]["kind"] == "money"
    assert updated["config"]["columns"][1]["configured"] is True
    assert updated["automatic_rows"] == [
        ["Erläuterung", "Fassung"],
        ["Kosten [Mio. €]", "Status"],
        ["1600000", "open"],
    ]
    assert updated["reviewed_rows"][2] == ["1600000", "approved"]
    assert updated["review_is_stale"] is True
    assert updated["is_confirmed"] is False
    assert (
        client.put(
            f"/api/clean-review/{clean_id}/rules",
            json={
                "config": {**updated["config"], "header_row": 4},
                "expected_clean_hash": updated["clean_hash"],
                "expected_source_hash": source_hash,
            },
        ).status_code
        == 422
    )

    copied_id = client.post("/api/clean-versions", json={"extract_id": 1}).json()["id"]
    copied = client.get(f"/api/clean-review/{copied_id}").json()
    assert copied["config"]["header_row"] == 2
    assert copied["automatic_rows"][2][0] == "1600000"
    scheme_id = client.post("/api/harmonize/schemes", json={"name": "New mapping"}).json()["id"]
    scheme = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    assert scheme["table_settings"]["1"]["header_row"] == 2


def test_deleted_rows_validation_and_grid() -> None:
    """Deleted rows must be data rows and are dropped from the cleaned grid."""
    globals_config = load_cleaning_globals(Path("config/cleaning.yaml"))
    rows = [["Name"], ["a"], ["b"], ["c"]]
    with pytest.raises(ValueError, match="cannot be deleted"):
        CleanConfig(header_row=1, deleted_rows=[0])
    config = CleanConfig(header_row=1, deleted_rows=[3, 1, 3])
    assert config.deleted_rows == [1, 3]
    cleaned, cells = clean_grid(rows, config, globals_config)
    assert cleaned == [["Name"], ["b"]]
    assert all(cell["row"] != 1 for cell in cells)


def test_deleting_and_restoring_rows_keeps_manual_edits(tmp_path: Path) -> None:
    """Row deletion recomputes the table and maps review edits by source row."""
    source = csv_bytes([["Status"], ["a"], ["b"], ["c"]])
    source_hash = write_bytes(tmp_path, "extracted/source.csv", source)
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'Provider', 'provider', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO document(id, dso_id, title, source, created_at, updated_at) "
            "VALUES (1, 1, 'NAP', 'test', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO extract_table(id, document_id, tool, table_number, "
            "extract_table_hash, extract_table_path, extract_created_at) "
            "VALUES (1, 1, 'docling', 1, ?, 'extracted/source.csv', '2026-01-01')",
            (source_hash,),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
    client = TestClient(create_app(tmp_path))
    clean_id = client.post("/api/clean-versions", json={"extract_id": 1}).json()["id"]
    first = client.get(f"/api/clean-review/{clean_id}").json()
    edited = [list(row) for row in first["rows"]]
    edited[3][0] = "C edited"
    client.put(
        f"/api/clean-review/{clean_id}",
        json={"rows": edited, "expected_clean_hash": first["clean_hash"], "confirm": False},
    )

    def set_deleted(rows: list[int]) -> dict:
        current = client.get(f"/api/clean-review/{clean_id}").json()
        response = client.put(
            f"/api/clean-review/{clean_id}/rules",
            json={
                "config": {**current["config"], "deleted_rows": rows},
                "expected_clean_hash": current["clean_hash"],
                "expected_source_hash": source_hash,
            },
        )
        assert response.status_code == 200
        return client.get(f"/api/clean-review/{clean_id}").json()

    deleted = set_deleted([1])
    assert deleted["kept_rows"] == [0, 2, 3]
    assert deleted["automatic_rows"] == [["Status"], ["b"], ["c"]]
    assert deleted["reviewed_rows"] == [["Status"], ["b"], ["C edited"]]
    restored = set_deleted([])
    assert restored["kept_rows"] == [0, 1, 2, 3]
    assert restored["reviewed_rows"] == [["Status"], ["a"], ["b"], ["C edited"]]
    current = client.get(f"/api/clean-review/{clean_id}").json()
    assert (
        client.put(
            f"/api/clean-review/{clean_id}/rules",
            json={
                "config": {**current["config"], "deleted_rows": [9]},
                "expected_clean_hash": current["clean_hash"],
                "expected_source_hash": source_hash,
            },
        ).status_code
        == 422
    )


@pytest.fixture
def preamble_client(tmp_path: Path) -> TestClient:
    """An app whose only extracted table has an empty preamble row above its header."""
    source = csv_bytes([[""], ["Kosten [Mio. €]", "Status"], ["1,6", "open"]])
    source_hash = write_bytes(tmp_path, "extracted/source.csv", source)
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'Provider', 'provider', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO document(id, dso_id, title, source, created_at, updated_at) "
            "VALUES (1, 1, 'NAP', 'test', '2026-01-01', '2026-01-01')"
        )
        database.execute(
            "INSERT INTO extract_table(id, document_id, tool, table_number, "
            "extract_table_hash, extract_table_path, extract_created_at) "
            "VALUES (1, 1, 'xlsx', 1, ?, 'extracted/source.csv', '2026-01-01')",
            (source_hash,),
        )
    return TestClient(create_app(tmp_path))


@pytest.mark.parametrize(("header_row", "status"), [(2, 201), (1, 422), (9, 422)])
def test_clean_version_uses_requested_header_row(
    preamble_client: TestClient, header_row: int, status: int
) -> None:
    """A table with a preamble gets its first version from the requested header row."""
    response = preamble_client.post(
        "/api/clean-versions", json={"extract_id": 1, "header_row": header_row}
    )
    assert response.status_code == status
    if status == 201:
        review = preamble_client.get(f"/api/clean-review/{response.json()['id']}").json()
        assert review["config"]["header_row"] == 2
        assert review["automatic_rows"][2][0] == "1600000"


def test_clean_version_header_row_overrides_previous_version(
    preamble_client: TestClient,
) -> None:
    """An explicit header row wins over the previous version's configuration."""
    first = preamble_client.post("/api/clean-versions", json={"extract_id": 1, "header_row": 2})
    reused = preamble_client.post("/api/clean-versions", json={"extract_id": 1}).json()
    assert first.json()["id"] != reused["id"]
    assert (
        preamble_client.get(f"/api/clean-review/{reused['id']}").json()["config"]["header_row"] == 2
    )
    overridden = preamble_client.post(
        "/api/clean-versions", json={"extract_id": 1, "header_row": 3}
    )
    assert overridden.status_code == 201
    review = preamble_client.get(f"/api/clean-review/{overridden.json()['id']}").json()
    assert review["config"]["header_row"] == 3
