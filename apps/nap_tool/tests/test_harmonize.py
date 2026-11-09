# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Scheme presets, version-specific bindings, and harmonized output."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nap_tool.data import sha256_file, write_bytes
from nap_tool.database.schema import connect
from nap_tool.harmonize import group_headers
from nap_tool.ui.harmonize_api import _build_output, _replace_output
from nap_tool.ui.server import create_app


def _prepare_sets(root: Path) -> None:
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO clean_table(extract_table_id,clean_table_hash,clean_table_path,"
            "clean_created_at,clean_updated_at) SELECT e.id,e.extract_table_hash,"
            "e.extract_table_path,'now','now' FROM extract_table e "
            "WHERE NOT EXISTS (SELECT 1 FROM clean_table c WHERE c.extract_table_id=e.id)"
        )
        for type_id in (1, 2):
            db.execute(
                "INSERT INTO harmonize_set(id,name,slug,table_type_id,created_at) "
                "VALUES (?,?,?,?, 'now')",
                (type_id, f"Type {type_id}", f"type_{type_id}", type_id),
            )
        # Give every fixture-created scheme an initial Set of its type.
        db.execute(
            "CREATE TRIGGER fixture_initial_set AFTER INSERT ON harmonize_scheme "
            "WHEN NEW.initial_set_id IS NULL BEGIN UPDATE harmonize_scheme "
            "SET initial_set_id=1 WHERE id=NEW.id; END"
        )


def test_lcs_groups_require_pairwise_similarity() -> None:
    """A third name cannot join through a merely transitive match."""
    assert group_headers(["abcd", "abce", "abef"], 0.75) == [["abcd", "abce"], ["abef"]]


def test_mixed_source_versions_align_by_row_number() -> None:
    """Each mapped column reads its own version, leaving missing rows empty."""
    fields = [
        {
            "title": "A",
            "sources": [{"extract_id": 1, "column_index": 0, "header": "A", "mode": "auto"}],
        },
        {
            "title": "B",
            "sources": [
                {
                    "extract_id": 1,
                    "column_index": 1,
                    "header": "B",
                    "mode": "fixed",
                    "stage": "extract_table",
                    "clean_id": None,
                    "source_hash": "old",
                }
            ],
        },
    ]
    tables = [
        {
            "extract_id": 1,
            "document_id": 2,
            "dso_slug": "network",
            "versions": [
                {
                    "stage": "clean_review",
                    "clean_id": 3,
                    "hash": "new",
                    "headers": ["A", "B"],
                    "rows": [["A", "B"], ["new-1", "x"], ["new-2", "y"]],
                },
                {
                    "stage": "extract_table",
                    "clean_id": None,
                    "hash": "old",
                    "headers": ["A", "B"],
                    "rows": [["A", "B"], ["old-1", "old-b"]],
                },
            ],
        }
    ]
    content, _, conflicts = _build_output(fields, tables)
    assert conflicts == 0
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    provenance = json.loads(rows[0]["source_cells_json"])
    assert "extract_table_id" not in rows[0]
    assert "row_number" not in rows[0]
    assert "record_granularity" not in rows[0]
    assert provenance["origin"]["extract_table_id"] == 1
    assert provenance["origin"]["row_number"] == 2
    assert len(provenance["sources"]) == 2
    assert provenance["sources"][0]["cells"] == ["new-1", "x"]
    assert provenance["sources"][1]["cells"] == ["old-1", "old-b"]
    missing = json.loads(rows[1]["source_cells_json"])["sources"][1]
    assert missing["row_exists"] is False
    assert missing["cells"] == []
    assert b"new-1,old-b" in content
    assert b"new-2," in content


def test_every_field_takes_its_value_from_its_bound_column() -> None:
    """A field with no bound column stays empty, whatever the table rules say."""
    fields = [
        {
            "key": key,
            "title": key,
            "sources": (
                [{"extract_id": 1, "column_index": index, "header": header, "mode": "auto"}]
                if header
                else []
            ),
        }
        for key, index, header in (
            ("measure_name", 0, "Name"),
            ("line_length_km", 1, "Länge"),
            ("asset_count", 0, ""),
            ("investment_total_eur", 0, ""),
        )
    ]
    tables = [
        {
            "extract_id": 1,
            "document_id": 2,
            "dso_slug": "network",
            # Rules the generator no longer honours; passing them must change nothing.
            "row_field_redirects": {3: {"line_length_km": "asset_count"}},
            "derived_values": {"investment_total_eur": "1"},
            "versions": [
                {
                    "stage": "clean_table",
                    "clean_id": 3,
                    "hash": "version-1",
                    "headers": ["Name", "Länge"],
                    "rows": [["Name", "Länge"], ["Cable", "8.2"], ["Station", "141"]],
                }
            ],
        }
    ]
    content, _, conflicts = _build_output(fields, tables)
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert conflicts == 0
    assert [row["line_length_km"] for row in rows] == ["8.2", "141"]
    assert {row["asset_count"] for row in rows} == {""}
    assert {row["investment_total_eur"] for row in rows} == {""}
    provenance = json.loads(rows[0]["source_cells_json"])
    assert provenance["sources"][0]["bindings"] == [
        {"field": "measure_name", "column_number": 1},
        {"field": "line_length_km", "column_number": 2},
    ]
    assert provenance["origin"]["document_id"] == 2
    assert "clean=3" in provenance["sources"][0]["review_path"]


def test_output_holds_only_values_that_stand_in_a_source_cell() -> None:
    """No field receives a value the generator made up for it."""
    fields = [
        {
            "key": "measure_name",
            "title": "measure_name",
            "sources": [{"extract_id": 1, "column_index": 0, "header": "Name", "mode": "auto"}],
        },
        {"key": "amount_kind", "title": "amount_kind", "sources": []},
        {"key": "time_window_label", "title": "time_window_label", "sources": []},
    ]
    tables = [
        {
            "extract_id": 1,
            "document_id": 2,
            "dso_slug": "network",
            # Rules a scheme can no longer express; passing them must change nothing.
            "derived_values": {"amount_kind": "measure"},
            "period_context_column": 0,
            "versions": [
                {
                    "stage": "clean_table",
                    "clean_id": 3,
                    "hash": "version-1",
                    "headers": ["Name"],
                    "rows": [["Name"], ["2024 bis 2028"], ["Cable"]],
                }
            ],
        }
    ]
    content, _, _ = _build_output(fields, tables)
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert [row["measure_name"] for row in rows] == ["2024 bis 2028", "Cable"]
    assert {row["amount_kind"] for row in rows} == {""}
    assert {row["time_window_label"] for row in rows} == {""}
    assert "period_context" not in json.loads(rows[0]["source_cells_json"])


def test_scheme_uses_selected_header_row_and_excludes_non_data_rows(tmp_path: Path) -> None:
    """Header and excluded rows are interpreted without rewriting the source CSV."""
    original = b"Group,Group\nName,Value\n2024 bis 2028,\nActual,4\nTotal,5\n"
    digest = write_bytes(tmp_path, "extracted/1.csv", original)
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) "
            "VALUES (1,'Provider','provider','now','now')"
        )
        database.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (1,1,'NAP','test','now','now')"
        )
        database.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,extract_created_at) "
            "VALUES (1,1,'llmPDF',1,?,'extracted/1.csv','now')",
            (digest,),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
    _prepare_sets(tmp_path)
    client = TestClient(create_app(tmp_path))
    scheme_id = client.post("/api/harmonize/schemes", json={"name": "Standard"}).json()["id"]
    scheme = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    updated = client.put(
        f"/api/harmonize/schemes/{scheme_id}",
        json={
            "name": "Standard",
            "fields": [
                {
                    "key": "measure_name",
                    "title": "Name",
                    "sources": [{"extract_id": 1, "column_index": 0, "header": "Name"}],
                },
            ],
            "table_settings": {
                "1": {
                    "header_row": 2,
                    "excluded_rows": [3, 5],
                }
            },
            "expected_updated_at": scheme["updated_at"],
        },
    )
    assert updated.status_code == 200
    inventory = client.get(f"/api/harmonize/inventory?scheme_id={scheme_id}").json()
    version = inventory["tables"][0]["versions"][0]
    assert version["headers"] == ["Name", "Value"]
    assert version["samples"][0] == ["Actual"]
    assert version["row_count"] == 1
    assert client.post(f"/api/harmonize/schemes/{scheme_id}/generate").status_code == 200
    preview = client.get(f"/api/harmonize/schemes/{scheme_id}/preview").json()
    assert preview["total_rows"] == 1
    assert preview["rows"][0][6] == "Actual"
    provenance = json.loads(preview["rows"][0][-1])
    assert provenance["sources"][0]["cells"] == ["Actual", "4"]
    assert provenance["sources"][0]["file_path"] == "extracted/1.csv"

    assert provenance["sources"][0]["file_hash"] == digest
    assert provenance["sources"][0]["header_row"] == 2
    assert (tmp_path / "extracted/1.csv").read_bytes() == original

    for mode in ("lcs80", "lcs60"):
        created = client.post(
            "/api/harmonize/schemes",
            json={
                "name": mode,
                "creation_mode": mode,
            },
        ).json()
        path = f"/api/harmonize/schemes/{created['id']}"
        before = client.get(path).json()
        assert before["fields"][0]["title"] == "Group"
        assert "preset_key" not in before
        assert (
            client.put(
                path,
                json={
                    "name": mode,
                    "fields": before["fields"],
                    "table_settings": before["table_settings"],
                    "expected_updated_at": before["updated_at"],
                },
            ).status_code
            == 200
        )


def test_set_table_type_selects_sources_for_a_reusable_scheme(tmp_path: Path) -> None:
    """A reusable scheme maps both types; the selected set controls generated rows."""
    measure_hash = write_bytes(tmp_path, "extracted/measure.csv", b"Name\nCable\n")
    regional_hash = write_bytes(tmp_path, "extracted/regional.csv", b"Parameter\nDemand\n")
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) "
            "VALUES (1,'Provider','provider','now','now')"
        )
        database.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (1,1,'NAP','test','now','now')"
        )
        database.executemany(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,extract_created_at) "
            "VALUES (?,1,'llmPDF',?,?,?,'now')",
            [
                (1, 1, measure_hash, "extracted/measure.csv"),
                (2, 2, regional_hash, "extracted/regional.csv"),
            ],
        )
        database.executemany("INSERT INTO extract_table_type VALUES (?,?)", [(1, 1), (2, 2)])
    _prepare_sets(tmp_path)
    client = TestClient(create_app(tmp_path))
    created = client.post("/api/harmonize/schemes", json={"name": "Regional", "initial_set_id": 2})
    assert created.status_code == 201
    scheme_id = created.json()["id"]
    assert "table_type" not in created.json()
    assert client.get(f"/api/harmonize/inventory?scheme_id={scheme_id}").json()["table_count"] == 2
    assert (
        client.get(f"/api/harmonize/inventory?scheme_id={scheme_id}").json()["tables"][0][
            "extract_id"
        ]
        == 1
    )
    scheme = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    update = {
        "name": "Regional",
        "fields": [
            {
                "key": "parameter",
                "title": "Parameter",
                "sources": [{"extract_id": 1, "column_index": 0, "header": "Name"}],
            }
        ],
        "expected_updated_at": scheme["updated_at"],
    }
    assert client.put(f"/api/harmonize/schemes/{scheme_id}", json=update).status_code == 200
    scheme = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    update["expected_updated_at"] = scheme["updated_at"]
    update["fields"][0]["sources"] = [{"extract_id": 2, "column_index": 0, "header": "Parameter"}]
    assert client.put(f"/api/harmonize/schemes/{scheme_id}", json=update).status_code == 200
    generated = client.post(f"/api/harmonize/schemes/{scheme_id}/generate")
    assert generated.status_code == 200
    assert generated.json()["tables"] == 1
    preview = client.get(f"/api/harmonize/schemes/{scheme_id}/preview").json()
    assert preview["rows"][0][6] == "Demand"
    provenance = json.loads(preview["rows"][0][-1])
    assert "table_type=2" in provenance["sources"][0]["review_path"]
    copied = client.post(
        "/api/harmonize/schemes", json={"name": "Regional copy", "copy_from_id": scheme_id}
    )
    assert copied.status_code == 201
    assert "table_type" not in copied.json()
    assert (
        client.post(
            "/api/harmonize/schemes",
            json={"name": "Wrong copy", "copy_from_id": scheme_id, "table_type": 1},
        ).status_code
        == 422
    )


def test_harmonize_presets_copy_and_fixed_source(tmp_path: Path) -> None:
    """A copied preset can bind a concrete extraction version and generate CSV."""
    original = b"Name,Wert\nOriginal,1\n"
    reviewed = b"Name,Wert\nReviewed,2\n"
    cleaned = b"Name,Wert\nCleaned,3\n"
    clean_review = b"Name,Wert\nChecked,4\n"
    hashes = [
        write_bytes(tmp_path, f"tables/{name}.csv", content)
        for name, content in (
            ("original", original),
            ("reviewed", reviewed),
            ("cleaned", cleaned),
            ("clean_review", clean_review),
        )
    ]
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) "
            "VALUES (1,'Provider','provider','now','now')"
        )
        database.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (1,1,'NAP','test','now','now')"
        )
        database.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,"
            "extract_reviewed_table_hash,extract_reviewed_table_path,extract_created_at) "
            "VALUES (1,1,'docling',1,?,?,?,?,'now')",
            (hashes[0], "tables/original.csv", hashes[1], "tables/reviewed.csv"),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
        database.execute(
            "INSERT INTO clean_table(id,extract_table_id,clean_table_hash,clean_table_path,"
            "clear_reviewed_table_hash,clear_reviewed_table_path,"
            "clean_created_at,clean_updated_at) "
            "VALUES (1,1,?,?,?,?,'now','now')",
            (hashes[2], "tables/cleaned.csv", hashes[3], "tables/clean_review.csv"),
        )
    _prepare_sets(tmp_path)
    client = TestClient(create_app(tmp_path))
    schemes = client.get("/api/harmonize/schemes").json()
    assert schemes == []
    schemes = [
        client.post(
            "/api/harmonize/schemes",
            json={
                "name": mode,
                "creation_mode": mode,
            },
        ).json()
        for mode in ("lcs80", "lcs60")
    ]
    inventory = client.get("/api/harmonize/inventory").json()
    assert inventory["tables"][0]["versions"][0]["stage"] == "clean_review"
    preset = client.get(f"/api/harmonize/schemes/{schemes[0]['id']}").json()
    assert len(preset["fields"]) == 2
    copied = client.post(
        "/api/harmonize/schemes",
        json={
            "name": "custom",
            "copy_from_id": schemes[0]["id"],
        },
    ).json()
    scheme = client.get(f"/api/harmonize/schemes/{copied['id']}").json()
    first = scheme["fields"][0]["sources"][0]
    first.update(
        {"mode": "fixed", "stage": "extract_table", "clean_id": None, "source_hash": hashes[0]}
    )
    updated = client.put(
        f"/api/harmonize/schemes/{copied['id']}",
        json={
            "name": "custom",
            "fields": scheme["fields"],
            "expected_updated_at": scheme["updated_at"],
        },
    )
    assert updated.status_code == 200
    mixed = client.post(f"/api/harmonize/schemes/{copied['id']}/generate")
    assert mixed.status_code == 200
    mixed_preview = client.get(f"/api/harmonize/schemes/{copied['id']}/preview").json()
    assert "Original" in mixed_preview["rows"][0]
    assert "4" in mixed_preview["rows"][0]
    assert len(json.loads(mixed_preview["rows"][0][-1])["sources"]) == 2
    assert not client.get(f"/api/harmonize/schemes/{copied['id']}").json()["output_is_stale"]
    output_dir = tmp_path / "harmonized/type_1"
    output = output_dir / (scheme["slug"] + ".csv")
    mixed_content = output.read_bytes()
    assert sha256_file(output) == mixed.json()["hash"]
    edited = client.get(f"/api/harmonize/schemes/{copied['id']}").json()
    for field in edited["fields"]:
        for source in field["sources"]:
            source.update(
                {
                    "mode": "fixed",
                    "stage": "extract_table",
                    "clean_id": None,
                    "source_hash": hashes[0],
                }
            )
    assert (
        client.put(
            f"/api/harmonize/schemes/{copied['id']}",
            json={
                "name": "custom",
                "fields": edited["fields"],
                "expected_updated_at": edited["updated_at"],
            },
        ).status_code
        == 200
    )
    generated = client.post(f"/api/harmonize/schemes/{copied['id']}/generate")
    assert generated.status_code == 200
    assert output.read_bytes() != mixed_content
    assert list(output_dir.iterdir()) == [output]
    with connect(tmp_path / "nap_tool.sqlite") as database:
        stored = database.execute(
            "SELECT output_path,output_hash FROM harmonize_set_output WHERE scheme_id=?",
            (copied["id"],),
        ).fetchone()
        assert stored["output_path"] == f"harmonized/type_1/{scheme['slug']}.csv"
        assert stored["output_hash"] == sha256_file(output) == generated.json()["hash"]
    # Concurrent regeneration must leave one complete file matching the database.
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(f"/api/harmonize/schemes/{copied['id']}/generate"), range(2)
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert list(output_dir.iterdir()) == [output]
    assert sha256_file(output) == generated.json()["hash"]
    preview = client.get(f"/api/harmonize/schemes/{copied['id']}/preview").json()
    assert preview["total_rows"] == 1
    assert "Original" in preview["rows"][0]
    assert client.get(f"/api/harmonize/schemes/{copied['id']}/download").status_code == 200
    latest = client.get(f"/api/harmonize/schemes/{copied['id']}").json()
    latest["fields"][0]["sources"].extend(latest["fields"][1]["sources"])
    latest["fields"].pop()
    saved = client.put(
        f"/api/harmonize/schemes/{copied['id']}",
        json={
            "name": latest["name"],
            "fields": latest["fields"],
            "expected_updated_at": latest["updated_at"],
        },
    )
    assert saved.status_code == 200
    assert client.get(f"/api/harmonize/schemes/{copied['id']}").json()["output_is_stale"]
    conflict = client.post(f"/api/harmonize/schemes/{copied['id']}/generate")
    assert conflict.json()["conflicts"] == 1
    merged = client.get(f"/api/harmonize/schemes/{copied['id']}/preview").json()
    assert '["Original","1"]' in merged["rows"][0]
    assert list(output_dir.iterdir()) == [output]


def test_header_rename_does_not_invalidate_column_binding(tmp_path: Path) -> None:
    """An automatic binding follows its column index when only its header changes."""
    original_hash = write_bytes(tmp_path, "tables/original.csv", b"Name,Value\nAlice,1\n")
    renamed_hash = write_bytes(tmp_path, "tables/renamed.csv", b"Renamed,Value\nAlice,1\n")
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) "
            "VALUES (1,'Provider','provider','now','now')"
        )
        database.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (1,1,'NAP','test','now','now')"
        )
        database.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,extract_created_at) "
            "VALUES (1,1,'docling',1,?,'tables/original.csv','now')",
            (original_hash,),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
    _prepare_sets(tmp_path)
    client = TestClient(create_app(tmp_path))
    scheme_id = client.post("/api/harmonize/schemes", json={"name": "Renamed header"}).json()["id"]
    detail = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    fields = [
        {
            "key": "name",
            "title": "Name",
            "sources": [{"extract_id": 1, "column_index": 0, "header": "Name"}],
        }
    ]
    assert (
        client.put(
            f"/api/harmonize/schemes/{scheme_id}",
            json={
                "name": "Renamed header",
                "fields": fields,
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/harmonize/schemes/{scheme_id}/generate").status_code == 200

    # A reviewed CSV becomes the preferred automatic source, with the same column at index 0.
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "UPDATE extract_table SET extract_reviewed_table_hash=?,"
            "extract_reviewed_table_path='tables/renamed.csv' WHERE id=1",
            (renamed_hash,),
        )
    detail = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    assert detail["output_is_stale"]
    assert detail["fields"][0]["sources"][0]["header"] == "Name"
    assert client.post(f"/api/harmonize/schemes/{scheme_id}/generate").status_code == 200
    detail = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    assert not detail["output_is_stale"]
    assert (
        client.put(
            f"/api/harmonize/schemes/{scheme_id}",
            json={
                "name": "Renamed header",
                "fields": detail["fields"],
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/harmonize/schemes/{scheme_id}/generate").status_code == 200
    assert not client.get(f"/api/harmonize/schemes/{scheme_id}").json()["output_is_stale"]
    preview = client.get(f"/api/harmonize/schemes/{scheme_id}/preview").json()
    assert preview["rows"][0][6] == "Alice"

    detail = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    detail["fields"][0]["sources"][0]["column_index"] = 2
    assert (
        client.put(
            f"/api/harmonize/schemes/{scheme_id}",
            json={
                "name": "Renamed header",
                "fields": detail["fields"],
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 422
    )
    detail["fields"][0]["sources"][0].update(
        {
            "column_index": 0,
            "mode": "fixed",
            "stage": "extract_reviewed",
            "source_hash": original_hash,
        }
    )
    assert (
        client.put(
            f"/api/harmonize/schemes/{scheme_id}",
            json={
                "name": "Renamed header",
                "fields": detail["fields"],
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 409
    )


@pytest.mark.parametrize("existing", [False, True])
def test_output_is_restored_if_database_commit_fails(tmp_path: Path, existing: bool) -> None:
    """A failed metadata commit rolls back the file and removes temporary artifacts."""
    relative = "harmonized/scheme_1/output.csv"
    output = tmp_path / relative
    if existing:
        write_bytes(tmp_path, relative, b"previous output")
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.executescript(
            "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
            "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id) "
            "DEFERRABLE INITIALLY DEFERRED);"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with ExitStack() as outputs, connect(tmp_path / "nap_tool.sqlite") as database:
            database.execute("BEGIN IMMEDIATE")
            outputs.enter_context(_replace_output(tmp_path, relative, b"new output"))
            assert output.read_bytes() == b"new output"
            database.execute("INSERT INTO child VALUES (123)")
    if existing:
        assert output.read_bytes() == b"previous output"
    else:
        assert not output.exists()
    assert list(output.parent.iterdir()) == ([output] if existing else [])
    with connect(tmp_path / "nap_tool.sqlite") as database:
        assert database.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0


def test_deleting_scheme_removes_its_fields(tmp_path: Path) -> None:
    """Deleting a scheme removes only its target fields and clears copy lineage."""
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) "
            "VALUES (1,'Provider','provider','now','now')"
        )
        database.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (1,1,'Document','test','now','now')"
        )
        database.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,extract_created_at) "
            "VALUES (10,1,'test',1,'hash','file.csv','now')"
        )
        database.execute(
            "INSERT INTO harmonize_scheme(id,name,created_at,updated_at) "
            "VALUES (4,'Original','now','now')"
        )
        database.execute(
            "INSERT INTO harmonize_scheme(id,name,copy_from_scheme_id,created_at,updated_at) "
            "VALUES (5,'Copy',4,'now','now')"
        )
        database.execute(
            "INSERT INTO harmonize_field(id,scheme_id,field_key,title,created_at,updated_at) "
            "VALUES (1,4,'name','Name','now','now'),"
            "(2,5,'name','Name','now','now')"
        )
        database.execute(
            "INSERT INTO harmonize_field_source(field_id,position,extract_id,column_index,header) "
            "VALUES (1,0,10,0,'Name'),(2,0,10,0,'Name')"
        )
    _prepare_sets(tmp_path)
    client = TestClient(create_app(tmp_path))
    assert client.delete("/api/harmonize/schemes/4").json() == {
        "deleted": True,
        "deleted_fields": 1,
    }
    with connect(tmp_path / "nap_tool.sqlite") as database:
        assert (
            database.execute("SELECT COUNT(*) FROM harmonize_field WHERE scheme_id=4").fetchone()[0]
            == 0
        )
        assert (
            database.execute("SELECT COUNT(*) FROM harmonize_field WHERE scheme_id=5").fetchone()[0]
            == 1
        )
        assert [
            row[0] for row in database.execute("SELECT field_id FROM harmonize_field_source")
        ] == [2]
        assert (
            database.execute(
                "SELECT copy_from_scheme_id FROM harmonize_scheme WHERE id=5"
            ).fetchone()[0]
            is None
        )


def test_excluded_rows_use_source_numbers_after_cleaning_deletes_rows(tmp_path: Path) -> None:
    """Deleting a row in cleaning does not shift harmonization row numbers."""
    digest = write_bytes(tmp_path, "extracted/1.csv", b"Name,Value\nA,1\nB,2\nC,3\nD,4\n")
    with connect(tmp_path / "nap_tool.sqlite") as database:
        database.execute(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) "
            "VALUES (1,'Provider','provider','now','now')"
        )
        database.execute(
            "INSERT INTO document(id,dso_id,title,source,created_at,updated_at) "
            "VALUES (1,1,'NAP','test','now','now')"
        )
        database.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,"
            "extract_table_hash,extract_table_path,extract_created_at) "
            "VALUES (1,1,'llmPDF',1,?,'extracted/1.csv','now')",
            (digest,),
        )
        database.execute("INSERT INTO extract_table_type VALUES (1,1)")
    _prepare_sets(tmp_path)
    client = TestClient(create_app(tmp_path))
    clean = client.post("/api/clean-versions", json={"extract_id": 1}).json()
    current = client.get(f"/api/clean-review/{clean['id']}").json()
    deleted = client.put(
        f"/api/clean-review/{clean['id']}/rules",
        json={
            "config": {**current["config"], "deleted_rows": [2]},
            "expected_clean_hash": current["clean_hash"],
            "expected_source_hash": current["source_hash"],
        },
    )
    assert deleted.status_code == 200
    scheme_id = client.post("/api/harmonize/schemes", json={"name": "Standard"}).json()["id"]
    scheme = client.get(f"/api/harmonize/schemes/{scheme_id}").json()
    updated = client.put(
        f"/api/harmonize/schemes/{scheme_id}",
        json={
            "name": "Standard",
            "fields": [
                {
                    "key": "measure_name",
                    "title": "Name",
                    "sources": [{"extract_id": 1, "column_index": 0, "header": "Name"}],
                }
            ],
            "table_settings": {"1": {"header_row": 1, "excluded_rows": [4]}},
            "expected_updated_at": scheme["updated_at"],
        },
    )
    assert updated.status_code == 200
    version = client.get(f"/api/harmonize/inventory?scheme_id={scheme_id}").json()["tables"][0][
        "versions"
    ][0]
    assert version["physical_row_count"] == 5
    assert version["samples"][0] == ["A", "D"]
    assert client.post(f"/api/harmonize/schemes/{scheme_id}/generate").status_code == 200
    preview = client.get(f"/api/harmonize/schemes/{scheme_id}/preview").json()
    assert [row[6] for row in preview["rows"]] == ["A", "D"]
    numbers = [json.loads(row[-1])["origin"]["row_number"] for row in preview["rows"]]
    assert numbers == [2, 5]
