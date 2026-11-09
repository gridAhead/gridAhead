# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for file-backed discovery, versioning, and legacy migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from nap_tool.data import checked_file
from nap_tool.database.migrate import migrate_database
from nap_tool.database.repository import (
    Candidate,
    create_download_run,
    documents_for_download,
    documents_for_extraction,
    record_download,
    store_candidates,
    store_extraction,
)
from nap_tool.database.schema import connect


def test_discover_download_and_force_version(tmp_path: Path) -> None:
    """A discovered document remains pending until downloaded and keeps versions."""
    database = tmp_path / "nap_tool.sqlite"
    candidate = Candidate(
        "sample-vnb", "Sample VNB", "custom", None, "NAP.pdf", "https://example.org/nap.pdf"
    )
    assert store_candidates(database, [candidate]) == (1, 0)
    assert store_candidates(database, [candidate]) == (0, 1)
    pending = documents_for_download(database, None, None, False)
    assert len(pending) == 1
    assert pending[0]["hash"] is None

    run_id = create_download_run(database, "nap-tool download")
    document_id, created = record_download(
        database, tmp_path, pending[0], b"%PDF-1.4\nfirst", run_id
    )
    assert created is True
    assert documents_for_download(database, None, None, False) == []
    selected = documents_for_extraction(database, None, None, "docling", False)
    assert [row["id"] for row in selected] == [document_id]
    assert checked_file(tmp_path, selected[0]["file_path"], selected[0]["hash"]).is_file()

    repeated_id, created = record_download(
        database, tmp_path, selected[0], b"%PDF-1.4\nfirst", run_id
    )
    assert (repeated_id, created) == (document_id, False)
    replacement_id, created = record_download(
        database, tmp_path, selected[0], b"%PDF-1.4\nsecond", run_id
    )
    assert created is True
    assert replacement_id != document_id
    with connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT is_selected FROM document WHERE id=?", (document_id,)
            ).fetchone()[0]
            == 0
        )


def test_extraction_creates_new_version_without_deleting_review(tmp_path: Path) -> None:
    """Forced extraction archives old output but keeps its review content."""
    database = tmp_path / "nap_tool.sqlite"
    candidate = Candidate("vnb", "VNB", "custom", None, "NAP.pdf", "https://example.org/nap.pdf")
    store_candidates(database, [candidate])
    pending = documents_for_download(database, None, None, False)[0]
    run_id = create_download_run(database, "download")
    document_id, _ = record_download(database, tmp_path, pending, b"%PDF-1.4\n", run_id)
    output = tmp_path / "staging"
    output.mkdir()
    (output / "table.csv").write_text("name,value\na,1\n", encoding="utf-8")
    metadata = {
        "provider_slug": "vnb",
        "source_sha256": hashlib.sha256(b"%PDF-1.4\n").hexdigest(),
        "generated_at": "2026-01-01T00:00:00Z",
        "tables": [{"table_number": 1, "file": "table.csv", "pages": [1], "regions": []}],
    }
    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert (
        store_extraction(
            database, tmp_path, document_id, "docling", output, "script.json", "a" * 64
        )
        == 1
    )
    with connect(database) as connection:
        connection.execute(
            "UPDATE extract_table SET extract_reviewed_table_path=?, extract_reviewed_table_hash=?",
            ("review.csv", "b" * 64),
        )
    metadata["generated_at"] = "2026-01-02T00:00:00Z"
    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert (
        store_extraction(
            database, tmp_path, document_id, "docling", output, "script.json", "a" * 64
        )
        == 1
    )
    with connect(database) as connection:
        rows = connection.execute(
            "SELECT extract_is_archived, extract_reviewed_table_path FROM extract_table ORDER BY id"
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [(1, "review.csv"), (0, None)]


def test_new_vnbdigital_document_replaces_selected_version(tmp_path: Path) -> None:
    """A newly discovered NAP supersedes the operator's previous NAP."""
    database = tmp_path / "nap_tool.sqlite"
    run_id = create_download_run(database, "download")
    for source_id, content in (("source-one", b"%PDF-one"), ("source-two", b"%PDF-two")):
        store_candidates(
            database,
            [
                Candidate(
                    "vnb",
                    "VNB",
                    "vnbdigital",
                    source_id,
                    "NAP.pdf",
                    f"https://example.org/{source_id}",
                )
            ],
        )
        pending = documents_for_download(database, None, None, False)
        assert len(pending) == 1
        record_download(database, tmp_path, pending[0], content, run_id)
    selected = documents_for_extraction(database, None, None, "docling", True)
    assert len(selected) == 1
    with connect(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM document WHERE is_selected=1").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    ("titles", "selected"),
    [
        (["NAP_2024.pdf", "NAP_2026.pdf"], ["NAP_2024.pdf", "NAP_2026.pdf"]),
        (
            ["NAP_2024.pdf", "NAP_2026_Entwurf.pdf", "NAP_2026_final.pdf"],
            ["NAP_2024.pdf", "NAP_2026_final.pdf"],
        ),
        (["NAP.pdf", "NAP_2026.pdf", "Bericht.pdf"], ["NAP_2026.pdf", "Bericht.pdf"]),
    ],
)
def test_new_vnbdigital_document_replaces_only_the_same_nap_year(
    tmp_path: Path, titles: list[str], selected: list[str]
) -> None:
    """A new NAP supersedes the operator's NAP of the same year and keeps other years."""
    database = tmp_path / "nap_tool.sqlite"
    run_id = create_download_run(database, "download")
    for number, title in enumerate(titles):
        candidate = Candidate(
            "vnb", "VNB", "vnbdigital", f"source-{number}", title, f"https://example.org/{number}"
        )
        store_candidates(database, [candidate])
        pending = documents_for_download(database, None, None, False)
        record_download(database, tmp_path, pending[0], f"%PDF-{number}".encode(), run_id)
    with connect(database) as connection:
        rows = connection.execute(
            "SELECT title FROM document WHERE is_selected=1 ORDER BY id"
        ).fetchall()
    assert [row[0] for row in rows] == selected


def test_migrate_minimal_legacy_database(tmp_path: Path) -> None:
    """Migration preserves every legacy stage and validates file hashes."""
    old = tmp_path / "old.sqlite"
    root = tmp_path / "new"
    root.mkdir()
    pdf = b"%PDF-1.4\nfixture"
    table = b"name,value\na,1\n"
    with sqlite3.connect(old) as connection:
        connection.executescript(
            "CREATE TABLE run(run_id INTEGER, run_datetime TEXT);"
            "CREATE TABLE vnb(provider_id INTEGER, provider_name TEXT, provider_slug TEXT);"
            "CREATE TABLE document(document_id INTEGER, vnb_id INTEGER, file BLOB, sha256 TEXT, "
            "current_from TEXT, current_to TEXT, source TEXT, source_url TEXT, "
            "document_name TEXT, nap_year INTEGER);"
            "CREATE TABLE run_document(run_id INTEGER, document_id INTEGER);"
            "CREATE TABLE extractor(extractor_id INTEGER, name TEXT);"
            "CREATE TABLE table_extracted(table_extracted_id INTEGER, document_id INTEGER, "
            "extractor_id INTEGER, data BLOB, table_number INTEGER, pages_json TEXT, "
            "regions_json TEXT, rows INTEGER, columns INTEGER, title TEXT, source_id TEXT, "
            "status TEXT, imported_from TEXT, source_markdown TEXT);"
            "CREATE TABLE table_review(review_id INTEGER, table_extracted_id INTEGER, mark TEXT, "
            "note TEXT, draft_json TEXT, history_json TEXT, source_data_sha256 TEXT, "
            "updated_at TEXT);"
            "CREATE TABLE table_compared(table_compared_id INTEGER, data BLOB, merged INTEGER, "
            "manually_edited INTEGER, ready INTEGER);"
            "CREATE TABLE comparison(table_extracted_id INTEGER, table_compared_id INTEGER);"
            "CREATE TABLE table_harmonized(table_harmonized_id INTEGER, table_compared_id INTEGER);"
            "CREATE TABLE extraction_review_source(document_id INTEGER, extractor_id INTEGER, "
            "map_json TEXT, output_markdown TEXT);"
        )
        connection.execute("INSERT INTO run VALUES (1, '2026-01-01')")
        connection.execute("INSERT INTO vnb VALUES (1, 'VNB', 'vnb')")
        connection.execute(
            "INSERT INTO document VALUES (1, 1, ?, ?, NULL, NULL, 'custom', ?, 'NAP.pdf', 2026)",
            (pdf, hashlib.sha256(pdf).hexdigest(), "https://example.org/nap.pdf"),
        )
        connection.execute("INSERT INTO run_document VALUES (1, 1)")
        connection.execute("INSERT INTO extractor VALUES (1, 'docling')")
        connection.execute(
            "INSERT INTO table_extracted VALUES (1, 1, 1, ?, 1, '[1]', '[]', 2, 2, NULL, "
            "'table-1', 'extracted', NULL, NULL)",
            (table,),
        )
        connection.execute(
            "INSERT INTO table_review VALUES (1, 1, 'approved', '', ?, '[]', ?, '2026-01-01')",
            (
                json.dumps({"rows": [["name", "value"], ["a", "1"]]}),
                hashlib.sha256(table).hexdigest(),
            ),
        )
        connection.execute("INSERT INTO table_compared VALUES (1, ?, 0, 0, 1)", (table,))
        connection.execute("INSERT INTO comparison VALUES (1, 1)")
        connection.execute("INSERT INTO table_harmonized VALUES (1, 1)")
        connection.execute("INSERT INTO extraction_review_source VALUES (1, 1, '{}', 'markdown')")

    counts = migrate_database(old, root)
    assert counts == {
        "document": 1,
        "extract_table": 1,
        "table_review": 1,
        "clean_table": 0,
        "measures_table": 1,
        "review_source": 1,
    }
    with connect(root / "nap_tool.sqlite") as connection:
        document = connection.execute("SELECT * FROM document").fetchone()
        extracted = connection.execute("SELECT * FROM extract_table").fetchone()
        cleaned = connection.execute("SELECT * FROM clean_table").fetchone()
        assert connection.execute("SELECT table_type_id FROM extract_table_type").fetchone()[0] == 1
        assert cleaned is None
        assert checked_file(root, document["file_path"], document["hash"]).read_bytes() == pdf
        assert (
            checked_file(
                root, extracted["extract_table_path"], extracted["extract_table_hash"]
            ).read_bytes()
            == table
        )


def test_extraction_and_download_skip_imported_non_pdf_documents(tmp_path: Path) -> None:
    """Locally imported workbooks and reports are neither extracted nor re-downloaded."""
    database = tmp_path / "nap_tool.sqlite"
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) "
            "VALUES (1, 'Provider', 'provider', '2026-01-01', '2026-01-01')"
        )
        for number, suffix in enumerate((".xlsx", ".md", ".pdf"), start=1):
            connection.execute(
                "INSERT INTO document(id, dso_id, title, hash, source, nap_year, file_path, "
                "created_at, updated_at) VALUES (?, 1, ?, ?, 'local_import', 2026, ?, "
                "'2026-01-01', '2026-01-01')",
                (number, f"file{suffix}", f"hash{number}", f"documents/provider/{number}{suffix}"),
            )
    extractable = documents_for_extraction(database, None, None, "docling", False)
    assert [row["title"] for row in extractable] == ["file.pdf"]
    assert documents_for_download(database, None, None, True) == []
