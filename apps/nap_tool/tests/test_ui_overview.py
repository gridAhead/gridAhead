# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Overview API integration tests with the file-backed metadata schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nap_tool.data import write_bytes
from nap_tool.database.schema import connect
from nap_tool.ui.server import create_app


@pytest.fixture
def overview_client(tmp_path: Path) -> TestClient:
    """Create a small, related pipeline for overview API tests.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        FastAPI test client.
    """
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'Avacon Netz GmbH', 'avacon', '2026-01-01', '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO document(id, dso_id, title, hash, source, file_path, "
            "created_at, updated_at) VALUES (5, 1, 'NAP.pdf', ?, 'custom', "
            "'pdf/avacon/doc.pdf', '2026-01-01', '2026-01-01')",
            ("a" * 64,),
        )
        for table_id, tool, table_type in ((11, "docling", None), (12, "llmPDF", 1)):
            connection.execute(
                "INSERT INTO extract_table(id, document_id, tool, table_number, "
                "pages, regions, extract_table_hash, "
                "extract_table_path, extract_table_notes, extract_created_at) "
                "VALUES (?, 5, ?, 1, '[2]', '[]', ?, ?, ?, '2026-01-01')",
                (
                    table_id,
                    tool,
                    "b" * 64,
                    f"extracted/{table_id}.csv",
                    json.dumps({"title": "Maßnahmen"}),
                ),
            )
            if table_type is not None:
                connection.execute(
                    "INSERT INTO extract_table_type VALUES (?,?)", (table_id, table_type)
                )
        connection.execute(
            "INSERT INTO clean_table(id, extract_table_id, clean_table_hash, "
            "clean_table_path, clean_table_notes, clean_is_confirmed, "
            "clean_created_at, clean_updated_at) "
            "VALUES (21, 12, ?, 'cleaned/21.csv', ?, 1, '2026-01-01', '2026-01-02')",
            ("c" * 64, json.dumps({"legacy_compared_id": 21})),
        )
    return TestClient(create_app(tmp_path))


def test_overview_hierarchy_and_filters(overview_client: TestClient) -> None:
    """The four columns return linked, filtered summaries."""
    summary = overview_client.get("/api/overview/summary").json()
    assert summary["extracted"] == 2
    assert summary["cleaned"] == 1
    assert "harmonize_schemes" not in summary
    vnbs = overview_client.get("/api/overview/vnbs").json()
    assert vnbs[0]["slug"] == "avacon"
    assert vnbs[0]["document_count"] == 1
    documents = overview_client.get("/api/overview/documents?vnb=avacon").json()
    assert [item["id"] for item in documents] == [5]
    filtered = overview_client.get(
        "/api/overview/extract-tables?document_id=5&tool=llmPDF&table_type=1"
    ).json()
    assert [item["id"] for item in filtered] == [12]
    assert filtered[0]["first_page"] == 2
    cleaned = overview_client.get("/api/overview/clean-tables?extract_id=12").json()
    assert cleaned[0]["is_legacy"] is True
    assert cleaned[0]["is_confirmed"] is True


def test_extract_scope_can_include_all_documents(
    overview_client: TestClient, tmp_path: Path
) -> None:
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (6,1,'Other.pdf','custom','2026-01-01','2026-01-01')"
        )
        connection.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,extract_created_at) "
            "VALUES (13,6,'docling',3,?,'extracted/13.csv','2026-01-01')",
            ("d" * 64,),
        )
    path = "/api/overview/extract-tables"
    scoped = overview_client.get(path + "?document_id=5").json()
    assert {item["id"] for item in scoped} == {11, 12}
    all_tables = overview_client.get(path).json()
    assert {item["id"] for item in all_tables} == {11, 12, 13}
    assert next(item for item in all_tables if item["id"] == 13)["document_title"] == "Other.pdf"
    assert {item["id"] for item in overview_client.get(path + "?table_type=1").json()} == {12}


def test_dso_identifiers_can_be_saved_and_read(overview_client: TestClient) -> None:
    response = overview_client.patch(
        "/api/overview/dsos/1/identifiers",
        json={"mastr_nr": " SNB990362338043 ", "bdew_code": "9907137000005"},
    )
    assert response.status_code == 200
    assert response.json()["mastr_nr"] == "SNB990362338043"
    assert response.json()["bdew_code"] == "9907137000005"
    assert overview_client.get("/api/overview/dsos").json()[0]["bdew_code"] == "9907137000005"


def test_documents_filter_by_report_year_across_vnbs(
    overview_client: TestClient, tmp_path: Path
) -> None:
    """A report year includes every VNB and takes precedence over update dates."""
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (2, 'Other Netz', 'other', '2026-01-01', '2026-01-01')"
        )
        connection.executemany(
            "INSERT INTO document(id, dso_id, title, source, version, "
            "nap_year, created_at, updated_at) "
            "VALUES (?, ?, ?, 'custom', ?, ?, '2026-01-01', '2026-01-01')",
            [
                (
                    6,
                    2,
                    "netzausbauplan_2024_stand_2025.pdf",
                    json.dumps({"current_from": "2025-07-22T22:00:00+00:00"}),
                    2024,
                ),
                (
                    7,
                    1,
                    "20250630_netzausbaubericht_2024.pdf",
                    json.dumps({"current_from": "2025-06-29T22:00:00+00:00"}),
                    2024,
                ),
                (
                    8,
                    1,
                    "netzausbauplan.pdf",
                    json.dumps({"current_from": "2021-12-31T23:00:00+00:00"}),
                    2022,
                ),
            ],
        )

    all_documents = overview_client.get("/api/overview/documents").json()
    assert len(all_documents) == 4
    assert {item["id"]: item["year"] for item in all_documents} == {
        5: None,
        6: 2024,
        7: 2024,
        8: 2022,
    }
    assert {item["dso_slug"] for item in all_documents} == {"avacon", "other"}
    selected_year = overview_client.get("/api/overview/documents?year=2024").json()
    assert {item["id"] for item in selected_year} == {6, 7}
    selected_vnb = overview_client.get("/api/overview/documents?vnb=other&year=2024").json()
    assert [item["id"] for item in selected_vnb] == [6]


@pytest.mark.parametrize(
    "path",
    [
        "/api/overview/documents?vnb=unknown",
        "/api/overview/extract-tables?document_id=999",
        "/api/overview/clean-tables?extract_id=999",
    ],
)
def test_overview_unknown_parent_returns_404(overview_client: TestClient, path: str) -> None:
    """Unknown parent selections do not silently return unrelated data."""
    assert overview_client.get(path).status_code == 404


def test_overview_serves_frontend(overview_client: TestClient) -> None:
    """FastAPI serves the built overview and redirects / and /ui."""
    page = overview_client.get("/ui/overview")
    assert page.status_code == 200
    assert "NAP Tool" in page.text
    assert overview_client.get("/ui/harmonize/result?scheme=1").status_code == 200
    assert overview_client.get("/ui/schema").status_code == 200
    assert overview_client.get("/ui/settings").status_code == 200
    assert overview_client.get("/ui/harmonize/sets").status_code == 200
    assert overview_client.get("/ui", follow_redirects=False).headers["location"] == "/ui/overview"
    assert overview_client.get("/", follow_redirects=False).headers["location"] == "/ui/overview"


def test_schema_describes_current_tables_and_relationships(
    overview_client: TestClient,
) -> None:
    """The diagram endpoint reflects the normalized source relationship."""
    response = overview_client.get("/api/schema")
    assert response.status_code == 200
    payload = response.json()
    tables = {table["name"]: table for table in payload["tables"]}
    assert len(tables) == 12
    assert "settings" not in {column["name"] for column in tables["harmonize_field"]["columns"]}
    assert tables["document"]["row_count"] == 1
    assert any(
        column["name"] == "dso_id" and column["is_foreign_key"]
        for column in tables["document"]["columns"]
    )
    assert {
        (relation["from_table"], relation["to_table"], relation["kind"])
        for relation in payload["relations"]
    } >= {
        ("harmonize_set", "harmonize_set_output", "foreign_key"),
        ("harmonize_scheme", "harmonize_set_output", "foreign_key"),
        ("harmonize_scheme", "harmonize_set", "foreign_key"),
        ("dso", "document", "foreign_key"),
        ("document", "extract_table", "foreign_key"),
        ("extract_table", "clean_table", "foreign_key"),
        ("extract_table", "harmonize_field_source", "foreign_key"),
        ("clean_table", "harmonize_field_source", "foreign_key"),
        ("harmonize_field", "harmonize_field_source", "foreign_key"),
    }


def test_document_pdf_opens_only_verified_file(overview_client: TestClient, tmp_path: Path) -> None:
    """Document links serve the stored PDF and reject missing or changed files."""
    path = "/api/overview/documents/5/pdf"
    assert overview_client.get("/api/overview/documents/999/pdf").status_code == 404
    assert overview_client.get(path).status_code == 409

    pdf = b"%PDF-1.4\n%%EOF\n"
    pdf_hash = write_bytes(tmp_path, "pdf/avacon/doc.pdf", pdf)
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE document SET hash=? WHERE id=5", (pdf_hash,))
    response = overview_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == pdf

    (tmp_path / "pdf/avacon/doc.pdf").write_bytes(b"changed")
    assert overview_client.get(path).status_code == 409


def test_spreadsheet_documents_download_as_table(
    overview_client: TestClient, tmp_path: Path
) -> None:
    """XLSX documents are offered as a table download, not as a PDF."""
    content = b"PK\x03\x04 xlsx"
    digest = write_bytes(tmp_path, "documents/avacon/list.xlsx", content)
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO document(id, dso_id, title, hash, source, file_path, "
            "created_at, updated_at) VALUES (6, 1, 'Massnahmen_2026.xlsx', ?, 'local_import', "
            "'documents/avacon/list.xlsx', '2026-01-01', '2026-01-01')",
            (digest,),
        )
    documents = overview_client.get("/api/overview/documents?vnb=avacon").json()
    assert {item["id"]: item["file_type"] for item in documents} == {5: "pdf", 6: "xlsx"}
    assert all("file_path" not in item for item in documents)
    response = overview_client.get("/api/overview/documents/6/table")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'attachment; filename="Massnahmen_2026.xlsx"' in response.headers["content-disposition"]
    assert overview_client.get("/api/overview/documents/6/pdf").status_code == 404
    assert overview_client.get("/api/overview/documents/5/table").status_code == 404
    assert overview_client.get("/api/overview/documents/999/table").status_code == 404


def test_markdown_documents_open_inline_as_text(
    overview_client: TestClient, tmp_path: Path
) -> None:
    """Markdown documents open in the browser as UTF-8 text, not as a download."""
    content = "## Netzausbauplan 2026 – Übersicht\n".encode()
    digest = write_bytes(tmp_path, "documents/avacon/nap.md", content)
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO document(id, dso_id, title, hash, source, file_path, "
            "created_at, updated_at) VALUES (7, 1, 'NAP_2026.md', ?, 'local_import', "
            "'documents/avacon/nap.md', '2026-01-01', '2026-01-01')",
            (digest,),
        )
    documents = overview_client.get("/api/overview/documents?vnb=avacon").json()
    assert {item["id"]: item["file_type"] for item in documents}[7] == "md"
    response = overview_client.get("/api/overview/documents/7/text")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    # No attachment header, so the browser displays the text.
    assert response.headers.get("content-disposition", "inline").startswith("inline")
    assert response.text == content.decode()
    assert overview_client.get("/api/overview/documents/5/text").status_code == 404
    assert overview_client.get("/api/overview/documents/7/pdf").status_code == 404
    (tmp_path / "documents/avacon/nap.md").write_text("changed", encoding="utf-8")
    assert overview_client.get("/api/overview/documents/7/text").status_code == 409


def test_extract_review_reads_pdf_and_saves_review(
    overview_client: TestClient, tmp_path: Path
) -> None:
    """A reviewer can edit a CSV without changing the extracted source."""
    pdf = b"%PDF-1.4\n%%EOF\n"
    source = b"Name,Value\nAlpha,1\n"
    pdf_hash = write_bytes(tmp_path, "pdf/avacon/doc.pdf", pdf)
    source_hash = write_bytes(tmp_path, "extracted/12.csv", source)
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE document SET hash=? WHERE id=5", (pdf_hash,))
        connection.execute(
            "UPDATE extract_table SET extract_table_hash=?, extract_table_path=?, regions=? "
            "WHERE id=12",
            (
                source_hash,
                "extracted/12.csv",
                json.dumps([{"page": 2, "bbox": [70, 150, 525, 435]}]),
            ),
        )

    review = overview_client.get("/api/extract-review/12")
    assert review.status_code == 200
    assert review.json()["rows"] == [["Name", "Value"], ["Alpha", "1"]]
    assert review.json()["source_rows"] == [["Name", "Value"], ["Alpha", "1"]]
    assert review.json()["reviewed_rows"] is None
    assert review.json()["pages"] == [2]
    assert review.json()["regions"] == [{"page": 2, "bbox": [70, 150, 525, 435]}]
    pdf_response = overview_client.get("/api/extract-review/12/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.content == pdf

    update = {
        "rows": [["Name", "Value"], ["Alpha", "2"]],
        "source_hash": source_hash,
        "reviewed_hash": None,
        "confirm": True,
    }
    saved = overview_client.put("/api/extract-review/12", json=update)
    assert saved.status_code == 200
    assert saved.json()["is_confirmed"] is True
    reread = overview_client.get("/api/extract-review/12").json()
    assert reread["rows"][1] == ["Alpha", "2"]
    assert reread["source_rows"][1] == ["Alpha", "1"]
    assert reread["reviewed_rows"][1] == ["Alpha", "2"]
    assert reread["is_confirmed"] is True
    assert (tmp_path / "extracted/12.csv").read_bytes() == source
    assert overview_client.put("/api/extract-review/12", json=update).status_code == 409

    unconfirmed = overview_client.put(
        "/api/extract-review/12",
        json={**update, "reviewed_hash": saved.json()["reviewed_hash"], "confirm": False},
    )
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["is_confirmed"] is False
    assert unconfirmed.json()["reviewed_hash"] == saved.json()["reviewed_hash"]
    assert overview_client.get("/api/extract-review/12").json()["is_confirmed"] is False

    reconfirmed = overview_client.put(
        "/api/extract-review/12",
        json={**update, "reviewed_hash": unconfirmed.json()["reviewed_hash"]},
    )
    assert reconfirmed.status_code == 200
    assert reconfirmed.json()["is_confirmed"] is True


def test_extract_review_rejects_modified_source(
    overview_client: TestClient, tmp_path: Path
) -> None:
    """A mismatched file hash prevents rendering tampered CSV content."""
    (tmp_path / "extracted").mkdir()
    (tmp_path / "extracted/12.csv").write_text("changed", encoding="utf-8")
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "UPDATE extract_table SET extract_table_path=? WHERE id=12",
            ("extracted/12.csv",),
        )
    assert overview_client.get("/api/extract-review/12").status_code == 409


def test_extract_review_metadata_actions(overview_client: TestClient, tmp_path: Path) -> None:
    """Measures selection, notes, and discard persist without deleting source data."""
    source_hash = write_bytes(tmp_path, "extracted/11.csv", b"Name\nAlpha\n")
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "UPDATE extract_table SET extract_table_hash=?, extract_reviewed_table_notes=? "
            "WHERE id=11",
            (source_hash, json.dumps({"legacy_review_id": 3})),
        )
    base = {"source_hash": source_hash, "reviewed_hash": None}
    endpoint = "/api/extract-review/11/metadata"

    marked = overview_client.patch(endpoint, json={**base, "table_type": 1})
    assert marked.status_code == 200
    assert marked.json()["table_type"] == 1
    assert overview_client.get("/api/overview/summary").json()["measures"] == 2

    regional = overview_client.patch(endpoint, json={**base, "table_type": 2})
    assert regional.status_code == 200
    assert regional.json()["table_type"] == 2
    assert overview_client.get("/api/overview/summary").json()["measures"] == 1
    assert [
        item["id"]
        for item in overview_client.get(
            "/api/overview/extract-tables?document_id=5&table_type=2"
        ).json()
    ] == [11]
    assert overview_client.patch(endpoint, json={**base, "table_type": 3}).status_code == 422
    unclassified = overview_client.patch(endpoint, json={**base, "table_type": None})
    assert unclassified.json()["table_type"] is None

    noted = overview_client.patch(endpoint, json={**base, "note": "Prüfung nötig: 2  rows"})
    assert noted.status_code == 200
    assert noted.json()["note"] == "Prüfung nötig: 2  rows"
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        notes = json.loads(
            connection.execute(
                "SELECT extract_reviewed_table_notes FROM extract_table WHERE id=11"
            ).fetchone()[0]
        )
    assert notes["legacy_review_id"] == 3

    discarded = overview_client.patch(endpoint, json={**base, "is_archived": True})
    assert discarded.status_code == 200
    assert discarded.json()["is_archived"] is True
    assert (tmp_path / "extracted/11.csv").is_file()
    assert overview_client.get("/api/extract-review/11").json()["is_archived"] is True
    assert (
        overview_client.patch(endpoint, json={**base, "is_archived": False}).json()["is_archived"]
        is False
    )

    assert (
        overview_client.patch(endpoint, json={**base, "note": "x", "is_archived": True}).status_code
        == 422
    )
    assert (
        overview_client.patch(
            endpoint, json={**base, "source_hash": "wrong", "note": "x"}
        ).status_code
        == 409
    )


def test_clean_filters_span_extractions_and_count_header_changes(
    overview_client: TestClient, tmp_path: Path
) -> None:
    """Filter saved differences and pending failures across extraction boundaries."""
    automatic = write_bytes(tmp_path, "cleaned/21.csv", b"Name,Value\nA,bad\nB,unknown\n")
    reviewed = write_bytes(tmp_path, "clean_reviewed/21.csv", b"Renamed,Value\nA,2\nC,unknown\n")
    cells = [{"row": row, "column": 1, "status": "unresolved"} for row in (1, 2)]
    statuses = write_bytes(tmp_path, "cleaned/21.cells.json", json.dumps(cells).encode())
    other_statuses = write_bytes(tmp_path, "cleaned/22.cells.json", json.dumps(cells[:1]).encode())
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "UPDATE clean_table SET clean_table_hash=?,clear_reviewed_table_path=?,"
            "clear_reviewed_table_hash=?,clean_cells_path=?,clean_cells_hash=? WHERE id=21",
            (automatic, "clean_reviewed/21.csv", reviewed, "cleaned/21.cells.json", statuses),
        )
        connection.execute(
            "INSERT INTO clean_table(id,extract_table_id,clean_table_path,clean_table_hash,"
            "clean_cells_path,clean_cells_hash,clean_created_at,clean_updated_at) "
            "VALUES (22,11,'cleaned/22.csv',?,'cleaned/22.cells.json',?,'now','now')",
            (automatic, other_statuses),
        )
    path = "/api/overview/clean-tables"
    manual = overview_client.get(path + "?manual=true").json()
    assert [item["id"] for item in manual] == [21]
    assert manual[0]["manual_count"] == 3  # Includes the edited header.
    assert manual[0]["unresolved_modified_count"] == 1
    assert manual[0]["pending_count"] == 1
    assert manual[0]["document_id"] == 5
    assert manual[0]["dso_slug"] == "avacon"
    modified = overview_client.get(path + "?unresolved_modified=true").json()
    assert [item["id"] for item in modified] == [21]
    pending = overview_client.get(path + "?unresolved=true").json()
    assert {item["extract_table_id"] for item in pending} == {11, 12}
    union = overview_client.get(path + "?manual=true&unresolved=true").json()
    assert {item["id"] for item in union} == {21, 22}
    scoped = overview_client.get(path + "?extract_id=11&manual=true").json()
    assert scoped == []


def test_custom_types_classification_and_deletion(
    overview_client: TestClient, tmp_path: Path
) -> None:
    client = overview_client
    types = client.get("/api/table-types").json()
    assert [(item["id"], item["name"]) for item in types] == [
        (1, "Maßnahmentabelle"),
        (2, "Regionale Szenarioparameter"),
    ]
    created = client.post("/api/table-types", json={"name": "  Custom type  "})
    assert created.status_code == 201
    type_id = created.json()["id"]
    assert created.json()["name"] == "Custom type"
    assert client.post("/api/table-types", json={"name": "custom TYPE"}).status_code == 409
    assert client.post("/api/table-types", json={"name": "   "}).status_code == 422
    digest = write_bytes(tmp_path, "extracted/11.csv", b"Name,Value\nCustom,42\n")
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE extract_table SET extract_table_hash=? WHERE id=11", (digest,))
    endpoint = "/api/extract-review/11/metadata"
    review = client.get("/api/extract-review/11").json()
    base = {"source_hash": review["source_hash"], "reviewed_hash": review["reviewed_hash"]}
    assigned = client.patch(endpoint, json={**base, "table_type": type_id})
    assert assigned.status_code == 200
    assert assigned.json()["table_type"] == type_id
    matches = client.get(f"/api/overview/extract-tables?table_type={type_id}").json()
    assert [item["id"] for item in matches] == [11]
    scheme_id = client.post("/api/harmonize/schemes", json={"name": "Custom mapping"}).json()["id"]
    other_digest = write_bytes(tmp_path, "extracted/12.csv", b"Name,Value\nOther,1\n")
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "UPDATE extract_table SET extract_table_hash=? WHERE id=12", (other_digest,)
        )
        connection.execute("UPDATE clean_table SET is_selected=0 WHERE id=21")
    inventory = client.get(f"/api/harmonize/inventory?scheme_id={scheme_id}").json()
    assert [item["extract_id"] for item in inventory["tables"]] == [11, 12]
    scheme = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    saved = client.put(
        f"/api/harmonize/schemes/{scheme_id}",
        json={
            "name": "Custom mapping",
            "expected_updated_at": scheme["updated_at"],
            "fields": [
                {
                    "key": "value",
                    "title": "Value",
                    "sources": [{"extract_id": 11, "column_index": 1, "header": "Value"}],
                }
            ],
        },
    )
    assert saved.status_code == 200
    selected_set = client.post(
        "/api/harmonize/sets", json={"name": "Custom tables", "table_type_id": type_id}
    ).json()
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO clean_table(extract_table_id,clean_table_hash,clean_table_path,"
            "clean_created_at,clean_updated_at) VALUES (11,?,'extracted/11.csv','now','now')",
            (digest,),
        )
    query = f"?set_id={selected_set['id']}"
    assert client.post(f"/api/harmonize/schemes/{scheme_id}/generate" + query).status_code == 200
    preview = client.get(f"/api/harmonize/schemes/{scheme_id}/preview" + query).json()
    assert preview["rows"][0][6] == "42"
    assert client.delete(f"/api/harmonize/schemes/{scheme_id}").status_code == 200
    assert client.delete(f"/api/table-types/{type_id}").status_code == 409
    assert client.patch(endpoint, json={**base, "table_type": 9999}).status_code == 422
    assert client.get("/api/extract-review/11").json()["table_type"] == type_id
    assert client.patch(endpoint, json={**base, "table_type": None}).status_code == 200
    assert client.delete(f"/api/harmonize/sets/{selected_set['id']}").status_code == 200
    assert client.delete(f"/api/table-types/{type_id}").status_code == 200
    assert client.delete(f"/api/table-types/{type_id}").status_code == 404
    assert client.get("/api/overview/extract-tables?table_type=bad").status_code == 422


def test_scheme_has_no_type_and_does_not_block_type_deletion(overview_client: TestClient) -> None:
    client = overview_client
    type_id = client.post("/api/table-types", json={"name": "Scheme type"}).json()["id"]
    scheme = client.post("/api/harmonize/schemes", json={"name": "Custom"})
    assert scheme.status_code == 201
    assert "table_type" not in scheme.json()
    assert client.delete(f"/api/table-types/{type_id}").status_code == 200
    assert (
        client.post(
            "/api/harmonize/schemes", json={"name": "Invalid", "table_type": 9999}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/harmonize/schemes/{scheme.json()['id']}").status_code == 200
    assert client.delete(f"/api/table-types/{type_id}").status_code == 404


def test_deleted_builtin_type_is_not_reused_or_reseeded(tmp_path: Path) -> None:
    with connect(tmp_path / "nap_tool.sqlite"):
        pass
    client = TestClient(create_app(tmp_path))
    assert client.delete("/api/table-types/1").status_code == 200
    assert client.delete("/api/table-types/2").status_code == 200
    assert client.get("/api/harmonize/schemes").json() == []
    created = client.post("/api/table-types", json={"name": "Only custom type"}).json()
    assert created["id"] > 2
    assert client.get("/api/harmonize/schemes").json() == []
    assert client.post("/api/harmonize/schemes", json={"name": "Custom"}).status_code == 201
