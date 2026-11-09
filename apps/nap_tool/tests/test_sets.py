# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP coverage for set management and live membership preview."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nap_tool.data import write_bytes
from nap_tool.database.schema import connect
from nap_tool.ui.server import create_app

ENDPOINT = "/api/harmonize/sets"


@pytest.fixture
def set_client(tmp_path: Path) -> TestClient:
    digest = write_bytes(tmp_path, "source.csv", b"Name,Value\nExample,1\n")
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.executemany(
            "INSERT INTO dso(id,name,slug,created_at,updated_at) VALUES (?,?,?,'now','now')",
            [(1, "VNB A", "a"), (2, "VNB B", "b")],
        )
        connection.executemany(
            "INSERT INTO document(id,dso_id,title,source,nap_year,created_at,updated_at) "
            "VALUES (?,?,'NAP','test',?,'now','now')",
            [
                (1, 1, 2024),
                (2, 1, 2025),
                (3, 2, 2024),
                (4, 2, None),
            ],
        )
        for extract_id, document_id, type_id, selected, archived, clean_selected in [
            (1, 1, 1, 1, 0, 1),
            (2, 2, 1, 1, 0, 1),
            (3, 3, 1, 1, 0, 1),
            (4, 4, 1, 1, 0, 1),
            (5, 3, 2, 1, 0, 1),
            (6, 1, 1, 0, 0, 1),
            (7, 1, 1, 1, 1, 1),
            (8, 1, 1, 1, 0, None),
            (9, 1, 1, 1, 0, 0),
        ]:
            connection.execute(
                "INSERT INTO extract_table(id,document_id,tool,table_number,is_selected,"
                "extract_is_archived,extract_table_hash,extract_table_path,extract_created_at) "
                "VALUES (?,?,'docling',?,?,?,?,'source.csv','now')",
                (extract_id, document_id, extract_id, selected, archived, digest),
            )
            connection.execute("INSERT INTO extract_table_type VALUES (?,?)", (extract_id, type_id))
            if clean_selected is not None:
                connection.execute(
                    "INSERT INTO clean_table(id,extract_table_id,is_selected,clean_table_hash,"
                    "clean_table_path,clean_created_at,clean_updated_at) "
                    "VALUES (?,?,?,?,'source.csv','now','now')",
                    (extract_id, extract_id, clean_selected, digest),
                )
        # Multiple selected cleaning versions must not double count an extraction.
        connection.execute(
            "INSERT INTO clean_table(id,extract_table_id,is_selected,clean_table_hash,"
            "clean_table_path,clean_created_at,clean_updated_at) "
            "VALUES (10,1,1,?,'source.csv','now','now')",
            (digest,),
        )
    return TestClient(create_app(tmp_path))


@pytest.mark.parametrize(
    "filters,counts",
    [
        ({"table_type_id": 1}, (4, 2, 1)),
        ({"table_type_id": 2}, (1, 1, 0)),
        ({"table_type_id": 1, "dso_ids": [1]}, (2, 1, 0)),
        ({"table_type_id": 1, "dso_ids": [2]}, (2, 1, 1)),
        ({"table_type_id": 1, "years": [2024]}, (2, 2, 1)),
        ({"table_type_id": 1, "years": [2024, 2025]}, (3, 2, 1)),
        ({"table_type_id": 1, "dso_ids": [2], "years": [2024]}, (1, 1, 1)),
        ({"table_type_id": 1, "years": [2023]}, (0, 0, 1)),
    ],
)
def test_set_preview_filters(set_client: TestClient, filters: dict, counts: tuple) -> None:
    response = set_client.post(ENDPOINT + "/preview", json=filters)
    assert response.status_code == 200
    result = response.json()
    assert (
        tuple(result[key] for key in ("table_count", "vnb_count", "undated_document_count"))
        == counts
    )
    assert result["zero_match"] == (counts[0] == 0)


def test_set_create_validation_and_type_deletion(set_client: TestClient) -> None:
    client = set_client
    response = client.post(
        ENDPOINT,
        json={
            "name": "  VNB A 2024  ",
            "table_type_id": 1,
            "dso_ids": [1, 1],
            "years": [2024, 2024],
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["name"] == "VNB A 2024"
    assert result["slug"] == "vnb_a_2024"
    assert result["dso_ids"] == [1]
    assert result["years"] == [2024]
    assert result["table_count"] == 1
    assert (
        client.post(
            ENDPOINT,
            json={
                "name": "vnb-a-2024",
                "table_type_id": 2,
            },
        ).status_code
        == 409
    )
    for invalid in [
        {"name": "Unknown type", "table_type_id": 999},
        {"name": "Unknown VNB", "table_type_id": 1, "dso_ids": [999]},
        {"name": "Invalid year", "table_type_id": 1, "years": [0]},
        {"name": " ", "table_type_id": 1},
    ]:
        assert client.post(ENDPOINT, json=invalid).status_code == 422
    empty = client.post(
        ENDPOINT,
        json={
            "name": "Future set",
            "table_type_id": 1,
            "years": [2030],
        },
    )
    assert empty.status_code == 201
    assert empty.json()["zero_match"]
    assert [item["id"] for item in client.get(ENDPOINT).json()] == [
        result["id"],
        empty.json()["id"],
    ]
    assert client.patch(ENDPOINT + f"/{result['id']}", json={"name": "Changed"}).status_code == 405

    custom_type = client.post("/api/table-types", json={"name": "Custom"}).json()["id"]
    custom_set = client.post(
        ENDPOINT, json={"name": "Custom set", "table_type_id": custom_type}
    ).json()
    registry_type = next(
        item for item in client.get("/api/table-types").json() if item["id"] == custom_type
    )
    assert registry_type["set_count"] == 1
    assert client.delete(f"/api/table-types/{custom_type}").status_code == 409
    assert client.delete(f"{ENDPOINT}/{custom_set['id']}").status_code == 200
    assert client.delete(f"/api/table-types/{custom_type}").status_code == 200


def test_set_membership_is_live_and_sets_can_overlap(
    set_client: TestClient, tmp_path: Path
) -> None:
    client = set_client
    created = client.post(
        ENDPOINT,
        json={
            "name": "Regional",
            "table_type_id": 2,
            "years": [2024],
        },
    ).json()
    overlapping = client.post(
        ENDPOINT,
        json={
            "name": "Regional VNB B",
            "table_type_id": 2,
            "dso_ids": [2],
        },
    ).json()
    assert created["table_count"] == overlapping["table_count"] == 1
    digest = client.get("/api/extract-review/1").json()["source_hash"]
    assert (
        client.patch(
            "/api/extract-review/1/metadata",
            json={
                "source_hash": digest,
                "table_type": 2,
            },
        ).status_code
        == 200
    )
    assert client.get(ENDPOINT).json()[0]["table_count"] == 2
    assert client.get(ENDPOINT).json()[1]["table_count"] == 1
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE clean_table SET is_selected=0 WHERE extract_table_id=1")
    assert client.get(ENDPOINT).json()[0]["table_count"] == 1
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE document SET nap_year=? WHERE id=3", (2025,))
    assert client.get(ENDPOINT).json()[0]["table_count"] == 0
    assert client.get(ENDPOINT).json()[1]["table_count"] == 1


def test_set_delete_preserves_schemes_and_options(set_client: TestClient) -> None:
    client = set_client
    assert client.get(ENDPOINT + "/options").json() == {
        "years": [2025, 2024],
        "vnbs": [{"id": 1, "name": "VNB A"}, {"id": 2, "name": "VNB B"}],
    }
    scheme = client.post("/api/harmonize/schemes", json={"name": "Reusable"}).json()
    created = client.post(ENDPOINT, json={"name": "Disposable", "table_type_id": 1}).json()
    assert client.delete(f"{ENDPOINT}/{created['id']}").status_code == 200
    assert client.delete(f"{ENDPOINT}/{created['id']}").status_code == 404
    assert client.get(f"/api/harmonize/schemes/{scheme['id']}").status_code == 200
    assert client.get(ENDPOINT).json() == []


def test_set_requires_selected_documents(set_client: TestClient, tmp_path: Path) -> None:
    client = set_client
    filters = {"table_type_id": 1, "years": [2024]}
    created = client.post(ENDPOINT, json={"name": "Selected 2024", **filters}).json()
    assert created["table_count"] == 2
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "INSERT INTO document(id,dso_id,title,source,nap_year,is_selected,"
            "created_at,updated_at) "
            "VALUES (5,1,'Another NAP','test',?,0,'now','now')",
            (2024,),
        )
        connection.execute(
            "INSERT INTO extract_table(id,document_id,tool,table_number,extract_table_hash,"
            "extract_table_path,extract_created_at) "
            "SELECT 10,5,'docling',10,extract_table_hash,extract_table_path,'now' "
            "FROM extract_table WHERE id=1"
        )
        connection.execute("INSERT INTO extract_table_type VALUES (10,1)")
        connection.execute(
            "INSERT INTO clean_table(id,extract_table_id,clean_table_hash,clean_table_path,"
            "clean_created_at,clean_updated_at) "
            "SELECT 11,10,clean_table_hash,clean_table_path,'now','now' FROM clean_table WHERE id=1"
        )
    assert client.post(ENDPOINT + "/preview", json=filters).json()["table_count"] == 2
    assert client.get(ENDPOINT).json()[0]["table_count"] == 2
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE document SET is_selected=1 WHERE id=5")
    assert client.get(ENDPOINT).json()[0]["table_count"] == 3
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE document SET is_selected=0 WHERE id IN (1,4,5)")
    assert client.post(ENDPOINT + "/preview", json=filters).json()["table_count"] == 1
    all_years = client.post(ENDPOINT + "/preview", json={"table_type_id": 1}).json()
    assert all_years["table_count"] == 2
    assert all_years["undated_document_count"] == 0


def test_scheme_set_associations(set_client: TestClient) -> None:
    client = set_client
    first = client.post(ENDPOINT, json={"name": "2024", "table_type_id": 1}).json()["id"]
    second = client.post(ENDPOINT, json={"name": "2025", "table_type_id": 1}).json()["id"]
    wrong_type = client.post(ENDPOINT, json={"name": "Regional", "table_type_id": 2}).json()["id"]
    scheme = client.post(
        "/api/harmonize/schemes",
        json={
            "name": "Shared",
            "initial_set_id": first,
        },
    ).json()
    path = f"/api/harmonize/schemes/{scheme['id']}"
    detail = client.get(path).json()
    assert detail["initial_set_id"] == first
    for invalid in (99999,):
        assert (
            client.put(
                path + "/initial-set",
                json={
                    "initial_set_id": invalid,
                    "expected_updated_at": detail["updated_at"],
                },
            ).status_code
            == 422
        )
    assert client.get(path).json()["initial_set_id"] == first
    changed = client.put(
        path + "/initial-set",
        json={
            "initial_set_id": second,
            "expected_updated_at": detail["updated_at"],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["initial_set_id"] == second
    assert (
        client.put(
            path + "/initial-set",
            json={
                "initial_set_id": None,
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/harmonize/schemes",
            json={"name": "Cross-type mapping", "initial_set_id": wrong_type},
        ).status_code
        == 201
    )
    client.delete(f"{ENDPOINT}/{second}")
    assert client.get(path).json()["initial_set_id"] is None
    assert (
        client.post(
            "/api/harmonize/schemes",
            json={
                "name": "Invalid",
                "initial_set_id": 99999,
            },
        ).status_code
        == 422
    )
    assert all(item["name"] != "Invalid" for item in client.get("/api/harmonize/schemes").json())


def test_generated_scheme_can_link_sets_without_editing_mapping(set_client: TestClient) -> None:
    client = set_client
    set_id = client.post(ENDPOINT, json={"name": "Preset set", "table_type_id": 1}).json()["id"]
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
    for preset in schemes:
        path = f"/api/harmonize/schemes/{preset['id']}"
        before = client.get(path).json()
        assert (
            client.put(
                path + "/initial-set",
                json={
                    "initial_set_id": set_id,
                    "expected_updated_at": before["updated_at"],
                },
            ).status_code
            == 200
        )
        after = client.get(path).json()
        assert after["fields"] == before["fields"]
        assert after["initial_set_id"] == set_id


def test_creation_modes_are_saved_editable_schemes(set_client: TestClient, tmp_path: Path) -> None:
    client = set_client
    assert client.get("/api/harmonize/schemes").json() == []
    created = []
    for mode in ("blank", "lcs80", "lcs60"):
        response = client.post(
            "/api/harmonize/schemes",
            json={
                "name": mode,
                "creation_mode": mode,
            },
        )
        assert response.status_code == 201
        path = f"/api/harmonize/schemes/{response.json()['id']}"
        detail = client.get(path).json()
        assert "preset_key" not in detail
        assert bool(detail["fields"]) == (mode != "blank")
        created.append(detail)
    original = created[1]
    copied = client.post(
        "/api/harmonize/schemes",
        json={
            "name": "Copy",
            "creation_mode": "copy",
            "copy_from_id": original["id"],
        },
    ).json()
    assert (
        client.get(f"/api/harmonize/schemes/{copied['id']}").json()["fields"] == original["fields"]
    )
    for body in (
        {"creation_mode": "copy"},
        {"creation_mode": "blank", "copy_from_id": original["id"]},
        {"creation_mode": "lcs80", "copy_from_id": original["id"]},
        {"creation_mode": "unknown"},
    ):
        assert (
            client.post("/api/harmonize/schemes", json={"name": "Invalid", **body}).status_code
            == 422
        )
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE extract_table SET is_selected=0")
    assert (
        client.get(f"/api/harmonize/schemes/{original['id']}").json()["fields"]
        == original["fields"]
    )
    assert client.delete(f"/api/harmonize/schemes/{original['id']}").status_code == 200
    assert len(client.get("/api/harmonize/schemes").json()) == 3


def test_inventory_marks_set_members(set_client: TestClient) -> None:
    client = set_client
    selected = client.post(
        ENDPOINT, json={"name": "2024", "table_type_id": 1, "years": [2024]}
    ).json()
    all_years = client.post(ENDPOINT, json={"name": "All years", "table_type_id": 1}).json()
    scheme_id = client.post(
        "/api/harmonize/schemes",
        json={"name": "Mapping", "creation_mode": "blank", "initial_set_id": selected["id"]},
    ).json()["id"]

    def members(query: str) -> set[int]:
        tables = client.get(f"/api/harmonize/inventory?{query}").json()["tables"]
        assert len(tables) > selected["table_count"]
        return {table["extract_id"] for table in tables if table["in_set"]}

    assert members(f"scheme_id={scheme_id}") == {1, 3}
    assert members(f"scheme_id={scheme_id}&set_id={all_years['id']}") == {1, 2, 3, 4}
    unscoped = client.get("/api/harmonize/inventory").json()["tables"]
    assert all(table["in_set"] for table in unscoped)
    assert client.get("/api/harmonize/inventory?set_id=99999").status_code == 404


def test_pair_generation_filters_outputs_and_tracks_membership(
    set_client: TestClient, tmp_path: Path
) -> None:
    client = set_client
    selected = client.post(
        ENDPOINT, json={"name": "2024", "table_type_id": 1, "years": [2024]}
    ).json()
    all_years = client.post(ENDPOINT, json={"name": "All years", "table_type_id": 1}).json()
    empty = client.post(
        ENDPOINT, json={"name": "Empty", "table_type_id": 1, "years": [2030]}
    ).json()
    regional = client.post(ENDPOINT, json={"name": "Regional", "table_type_id": 2}).json()
    created = client.post(
        "/api/harmonize/schemes",
        json={
            "name": "Mapping",
            "creation_mode": "lcs80",
            "initial_set_id": selected["id"],
        },
    ).json()
    path = f"/api/harmonize/schemes/{created['id']}"
    assert client.post(path + "/generate").json()["tables"] == selected["table_count"] == 2
    initial = client.get(path).json()
    assert initial["has_output"] and not initial["output_is_stale"]
    preview = client.get(path + "/preview").json()
    assert preview["header"][:6] == [
        "dso_slug",
        "nap_year",
        "document_key",
        "extractor",
        "table_number",
        "row_number",
    ]
    assert {row[1] for row in preview["rows"]} == {"2024"}
    assert {row[0] for row in preview["rows"]} == {"a", "b"}
    assert {row[5] for row in preview["rows"]} == {"2"}
    initial_output = tmp_path / "harmonized/2024/mapping.csv"
    initial_bytes = initial_output.read_bytes()
    assert client.get(path + "/download").content == initial_bytes
    other = f"?set_id={all_years['id']}"
    assert not client.get(path + other).json()["has_output"]
    assert client.post(path + "/generate" + other).json()["tables"] == all_years["table_count"] == 4
    assert (tmp_path / "harmonized/all_years/mapping.csv").exists()
    assert initial_output.read_bytes() == initial_bytes
    assert (
        client.post(path + f"/generate?set_id={empty['id']}").json()["detail"]
        == "Set has no tables"
    )
    assert not (tmp_path / "harmonized/empty/mapping.csv").exists()
    assert client.post(path + f"/generate?set_id={regional['id']}").status_code == 200
    # Membership changes affect each combination independently.
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE document SET is_selected=0 WHERE id=2")
    assert not client.get(path).json()["output_is_stale"]
    assert client.get(path + other).json()["output_is_stale"]
    assert client.post(path + "/generate" + other).json()["tables"] == 3
    # Selected cleaning changes affect every pair containing that table.
    digest = write_bytes(tmp_path, "updated.csv", b"Name,Value\nChanged,9\n")
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute(
            "UPDATE clean_table SET clean_table_hash=?,clean_table_path='updated.csv' WHERE id=10",
            (digest,),
        )
    assert client.get(path).json()["output_is_stale"]
    assert client.get(path + other).json()["output_is_stale"]
    assert client.post(path + "/generate").status_code == 200
    assert not client.get(path).json()["output_is_stale"]
    assert client.delete(f"{ENDPOINT}/{selected['id']}").status_code == 200
    assert not initial_output.exists()
    assert client.get(path).json()["initial_set_id"] is None
    assert (tmp_path / "harmonized/all_years/mapping.csv").exists()
    assert client.delete(path).status_code == 200
    assert not (tmp_path / "harmonized/all_years/mapping.csv").exists()


def test_pair_scheme_edits_and_unrelated_source_files(
    set_client: TestClient, tmp_path: Path
) -> None:
    client = set_client
    selected = client.post(
        ENDPOINT, json={"name": "VNB A", "table_type_id": 1, "dso_ids": [1], "years": [2024]}
    ).json()
    scheme = client.post(
        "/api/harmonize/schemes",
        json={"name": "Map", "creation_mode": "lcs60", "initial_set_id": selected["id"]},
    ).json()
    path = f"/api/harmonize/schemes/{scheme['id']}"
    assert client.post(path + "/generate").json()["tables"] == 1
    detail = client.get(path).json()
    assert (
        client.put(
            path,
            json={
                "name": detail["name"],
                "fields": detail["fields"][:1],
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 200
    )
    assert client.get(path).json()["output_is_stale"]
    assert client.post(path + "/generate").status_code == 200
    assert (tmp_path / "harmonized/vnb_a/map.csv").exists()
    assert not (tmp_path / "harmonized/vnb_a/renamed.csv").exists()
    # An unavailable file outside the chosen set cannot block its generation.
    with connect(tmp_path / "nap_tool.sqlite") as connection:
        connection.execute("UPDATE extract_table SET extract_table_path='missing.csv' WHERE id=3")
    assert client.post(path + "/generate").status_code == 200


def test_scheme_names_unique_and_immutable(set_client: TestClient) -> None:
    client = set_client
    scheme = client.post(
        "/api/harmonize/schemes", json={"name": "Yearly Measures", "creation_mode": "lcs80"}
    ).json()
    assert (
        client.post("/api/harmonize/schemes", json={"name": "yearly-measures"}).status_code == 409
    )
    assert client.post("/api/harmonize/schemes", json={"name": "   "}).status_code == 422
    path = f"/api/harmonize/schemes/{scheme['id']}"
    detail = client.get(path).json()
    assert (
        client.put(
            path,
            json={"name": "Renamed", "fields": [], "expected_updated_at": detail["updated_at"]},
        ).status_code
        == 422
    )
    unchanged = client.get(path).json()
    assert unchanged["name"] == detail["name"]
    assert unchanged["fields"] == detail["fields"]
    assert unchanged["updated_at"] == detail["updated_at"]
    for action in ("generate", "preview", "download"):
        response = (
            client.post(path + "/" + action)
            if action == "generate"
            else client.get(path + "/" + action)
        )
        assert response.status_code == 422
    assert (
        client.put(
            path,
            json={
                "name": detail["name"],
                "fields": detail["fields"],
                "expected_updated_at": detail["updated_at"],
            },
        ).status_code
        == 200
    )


def test_edit_document_year_updates_membership_and_staleness(
    set_client: TestClient, tmp_path: Path
) -> None:
    client = set_client
    selected = client.post(
        ENDPOINT, json={"name": "2024", "table_type_id": 1, "years": [2024]}
    ).json()
    all_years = client.post(ENDPOINT, json={"name": "All", "table_type_id": 1}).json()
    scheme = client.post(
        "/api/harmonize/schemes", json={"name": "Year map", "creation_mode": "lcs80"}
    ).json()
    path = f"/api/harmonize/schemes/{scheme['id']}"
    for item in (selected, all_years):
        assert client.post(path + f"/generate?set_id={item['id']}").status_code == 200
    with connect(tmp_path / "nap_tool.sqlite") as db:
        db.execute(
            "UPDATE document SET version=? WHERE id=1",
            ("2024-04-01",),
        )
    document = next(
        item for item in client.get("/api/overview/documents").json() if item["id"] == 1
    )
    endpoint = "/api/overview/documents/1/year"
    body = {"nap_year": 2025, "expected_updated_at": document["updated_at"]}
    response = client.patch(endpoint, json=body)
    assert response.status_code == 200
    assert client.patch(endpoint, json=body).status_code == 409
    assert (
        next(item for item in client.get(ENDPOINT).json() if item["id"] == selected["id"])[
            "table_count"
        ]
        == 1
    )
    for item in (selected, all_years):
        assert client.get(path + f"?set_id={item['id']}").json()["output_is_stale"]
    with connect(tmp_path / "nap_tool.sqlite") as db:
        document = db.execute("SELECT version,nap_year FROM document WHERE id=1").fetchone()
        assert tuple(document) == ("2024-04-01", 2025)
    assert (
        client.patch(
            endpoint, json={"nap_year": None, "expected_updated_at": response.json()["updated_at"]}
        ).status_code
        == 200
    )
    updated = next(item for item in client.get("/api/overview/documents").json() if item["id"] == 1)
    assert updated["year"] is None
    assert 1 not in [item["id"] for item in client.get("/api/overview/documents?year=2024").json()]
    assert client.get(ENDPOINT + "/options").json()["years"] == [2025, 2024]
    preview = client.post(ENDPOINT + "/preview", json={"table_type_id": 1}).json()
    assert preview["table_count"] == 4 and preview["undated_document_count"] == 2
    for invalid in (1999, 2101, 2024.5, True, "2024"):
        assert (
            client.patch(
                endpoint, json={"nap_year": invalid, "expected_updated_at": updated["updated_at"]}
            ).status_code
            == 422
        )
    assert (
        client.patch(
            "/api/overview/documents/999/year",
            json={"nap_year": 2024, "expected_updated_at": "now"},
        ).status_code
        == 404
    )


def test_year_edit_preserves_plain_version_and_survives_discovery(
    set_client: TestClient, tmp_path: Path
) -> None:
    from nap_tool.database.repository import Candidate, store_candidates

    candidate = Candidate(
        "pending", "Pending", "test", None, "NAP 2024", "https://example.org/nap.pdf", "2024-04-01"
    )
    assert store_candidates(tmp_path / "nap_tool.sqlite", [candidate]) == (1, 0)
    document = next(
        item
        for item in set_client.get("/api/overview/documents").json()
        if item["dso_slug"] == "pending"
    )
    response = set_client.patch(
        f"/api/overview/documents/{document['id']}/year",
        json={"nap_year": 2100, "expected_updated_at": document["updated_at"]},
    )
    assert response.status_code == 200
    assert store_candidates(tmp_path / "nap_tool.sqlite", [candidate]) == (0, 1)
    updated = next(
        item
        for item in set_client.get("/api/overview/documents").json()
        if item["id"] == document["id"]
    )
    assert updated["year"] == 2100
    assert updated["version"] == "2024-04-01"


def test_existing_null_year_keeps_inference_until_explicitly_cleared():
    from nap_tool.document_metadata import infer_nap_year as _document_year

    assert _document_year("NAP 2024", '{"nap_year":null}') == 2024
    assert _document_year("NAP 2024", '{"nap_year":null,"nap_year_is_manual":true}') is None


def test_set_default_scheme_validation_and_delete_guard(set_client: TestClient) -> None:
    client = set_client
    selected = client.post(ENDPOINT, json={"name": "Default", "table_type_id": 1}).json()
    scheme = client.post(
        "/api/harmonize/schemes", json={"name": "Default map", "creation_mode": "blank"}
    ).json()
    other = client.post(
        "/api/harmonize/schemes",
        json={"name": "Other map", "creation_mode": "blank"},
    ).json()
    endpoint = f"{ENDPOINT}/{selected['id']}/current-scheme"
    body = {"current_scheme_id": scheme["id"], "expected_current_scheme_id": None}
    assert client.put(endpoint, json={**body, "current_scheme_id": other["id"]}).status_code == 200
    body["expected_current_scheme_id"] = other["id"]
    assert client.put(endpoint, json={**body, "current_scheme_id": 999}).status_code == 422
    assert client.put(endpoint, json=body).json()["current_scheme_id"] == scheme["id"]
    assert client.put(endpoint, json=body).status_code == 409
    assert client.delete(f"/api/harmonize/schemes/{scheme['id']}").status_code == 409
    assert (
        client.put(
            endpoint, json={"current_scheme_id": None, "expected_current_scheme_id": scheme["id"]}
        ).status_code
        == 200
    )
    assert client.delete(f"/api/harmonize/schemes/{scheme['id']}").status_code == 200


def test_set_edits_preserve_identity_and_invalidate_only_changed_filters(set_client, tmp_path):
    client = set_client
    selected = client.post(ENDPOINT, json={"name": "Editable", "table_type_id": 1}).json()
    set_id = selected["id"]
    with connect(tmp_path / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO harmonize_scheme(id,name,initial_set_id,created_at,updated_at) "
            "VALUES (99,'Mapping',?,'now','now')",
            (set_id,),
        )
        db.execute("UPDATE harmonize_set SET current_scheme_id=99 WHERE id=?", (set_id,))
        db.execute(
            "INSERT INTO harmonize_set_output VALUES (?,99,'output.csv','hash','manifest','now')",
            (set_id,),
        )
    body = {"name": "Renamed", "table_type_id": 1, "dso_ids": [], "years": []}
    renamed = client.put(f"{ENDPOINT}/{set_id}", json=body)
    assert renamed.status_code == 200
    assert renamed.json()["id"] == set_id
    assert renamed.json()["current_scheme_id"] == 99
    with connect(tmp_path / "nap_tool.sqlite") as db:
        assert (
            db.execute("SELECT source_manifest_hash FROM harmonize_set_output").fetchone()[0]
            == "manifest"
        )
    filtered = client.put(f"{ENDPOINT}/{set_id}", json={**body, "dso_ids": [2], "years": [2024]})
    assert filtered.status_code == 200
    assert filtered.json()["table_count"] == 1
    assert filtered.json()["vnb_count"] == 1
    with connect(tmp_path / "nap_tool.sqlite") as db:
        output = db.execute("SELECT * FROM harmonize_set_output").fetchone()
        assert output["source_manifest_hash"] is None
        assert output["output_hash"] == "hash"
    assert client.put(f"{ENDPOINT}/{set_id}", json={**body, "table_type_id": 2}).status_code == 200
    assert client.get(ENDPOINT).json()[0]["table_type_id"] == 2


def test_set_edit_validation_is_atomic(set_client):
    client = set_client
    a = client.post(ENDPOINT, json={"name": "First", "table_type_id": 1}).json()
    client.post(ENDPOINT, json={"name": "Other", "table_type_id": 1})
    endpoint = f"{ENDPOINT}/{a['id']}"
    for body, status in [
        ({"name": "Other", "table_type_id": 1}, 409),
        ({"name": "   ", "table_type_id": 1}, 422),
        ({"name": "First", "table_type_id": 1, "dso_ids": [999]}, 422),
    ]:
        assert client.put(endpoint, json=body).status_code == status
        assert client.get(ENDPOINT).json()[0] == {k: v for k, v in a.items() if k != "zero_match"}
    assert (
        client.put(ENDPOINT + "/999", json={"name": "Missing", "table_type_id": 1}).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [("Maßnahmentabelle 2026", True), ("Szenarioparameter 2026", False)],
)
def test_set_summary_flags_grid_measure_types(
    set_client: TestClient, type_name: str, expected: bool
) -> None:
    type_id = set_client.post("/api/table-types", json={"name": type_name}).json()["id"]
    created = set_client.post(
        ENDPOINT, json={"name": "Flagged", "table_type_id": type_id, "dso_ids": [], "years": []}
    ).json()
    assert created["is_grid_measure"] is expected
    listed = {item["id"]: item for item in set_client.get(ENDPOINT).json()}
    assert listed[created["id"]]["is_grid_measure"] is expected
