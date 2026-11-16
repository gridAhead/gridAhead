# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Real metadata/CSV integration shared by CLI and UI."""

import csv
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from filelock import FileLock
from typer.testing import CliRunner

from nap_tool.classifier.config import load_config
from nap_tool.classifier.service import (
    CONFIG_PATH,
    OUTPUT_FILES,
    output_status,
    published_directory,
    run,
    year_config_path,
)
from nap_tool.cli import app
from nap_tool.data import sha256_file
from nap_tool.database.schema import connect
from nap_tool.ui.server import create_app


def current_output(root: Path, scheme_id: int = 1, set_id: int = 1) -> Path:
    """Re-read the pointer, so a later run is seen rather than a pinned generation."""
    return published_directory(root / f"classified/set_{set_id}", scheme_id)


@pytest.fixture
def repository(tmp_path):
    config = load_config()
    headers = list(config.required_fields)
    # Verify display titles can be mapped to stable keys without changing the original CSV.
    headers[headers.index("measure_name")] = "Maßnahme"
    values = dict.fromkeys(headers, "")
    values.update(
        dso_slug="test",
        measure_description="Kabelneubau",
        **{"Maßnahme": "Neubau 20 kV Kabel"},
    )
    values["source_cells_json"] = json.dumps(
        {
            "origin": {
                "extract_table_id": 1,
                "row_number": 2,
                "document_id": 1,
                "currentFrom": "2024-04-01",
                "clean_is_confirmed": True,
            },
            "sources": [],
        }
    )
    path = tmp_path / "harmonized/scheme_1/output.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, headers)
        writer.writeheader()
        writer.writerow(values)
    with connect(tmp_path / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO dso(name,slug,mastr_nr,bdew_code,created_at,updated_at) "
            "VALUES ('Test','test','ABC','123','now','now')"
        )
        db.execute(
            "INSERT INTO harmonize_set(id,name,slug,table_type_id,created_at) "
            "VALUES (1,'Test','test',1,'now')"
        )
        db.execute(
            "INSERT INTO harmonize_scheme(id,name,initial_set_id,created_at,updated_at) "
            "VALUES (1,'Test',1,'now','now')"
        )
        db.execute(
            "INSERT INTO harmonize_field(scheme_id,field_key,title,position,created_at,updated_at) "
            "VALUES (1,'measure_name','Maßnahme',1,'now','now')"
        )
        from nap_tool.ui.harmonize_api import _fields, _pair_manifest, _pair_tables

        scheme = db.execute("SELECT * FROM harmonize_scheme WHERE id=1").fetchone()
        tables = _pair_tables(db, tmp_path, scheme, 1)
        manifest = _pair_manifest(_fields(db, scheme, tables), tables)
        db.execute(
            "INSERT INTO harmonize_set_output VALUES (1,1,?,?,?,'now')",
            (str(path.relative_to(tmp_path)), sha256_file(path), manifest),
        )
    return tmp_path, path, values


def test_files_provenance_determinism_and_staleness(repository):
    root, source, original = repository
    before = source.read_bytes()
    metadata_before = (root / "nap_tool.sqlite").read_bytes()
    result = run(root, 1)
    first = {file: (current_output(root) / file).read_bytes() for file in OUTPUT_FILES}
    assert result.rows[0]["source_cells_json"] == original["source_cells_json"]
    assert result.rows[0]["Maßnahme"] == original["Maßnahme"]
    assert result.rows[0]["dso_mastr_nr"] == "ABC"
    assert result.rows[0]["inferred_asset_type"] == "cable"
    assert source.read_bytes() == before
    assert (root / "nap_tool.sqlite").read_bytes() == metadata_before
    assert not output_status(root, 1)["stale"]
    run(root, 1)
    assert first == {file: (current_output(root) / file).read_bytes() for file in OUTPUT_FILES}
    with connect(root / "nap_tool.sqlite") as db:
        db.execute("UPDATE dso SET bdew_code='456'")
    assert output_status(root, 1)["stale"]
    source.write_text("modified", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing or modified"):
        run(root, 1)
    assert first == {file: (current_output(root) / file).read_bytes() for file in OUTPUT_FILES}


@pytest.mark.parametrize("status,code", [("pass", 0), ("warn", 3), ("fail", 4)])
def test_cli_exit_codes(repository, monkeypatch, tmp_path, status, code):
    root, _, _ = repository
    config = yaml.safe_load(Path("config/classify.yaml").read_text(encoding="utf-8"))
    config["validation"]["dso_count"] = {
        "pass": [1, 1] if status == "pass" else [2, 2],
        "warn": [1, 2] if status != "fail" else [2, 3],
    }
    path = tmp_path / "classify.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("NAP_DATA_DIR", str(root))
    result = CliRunner().invoke(app, ["classify", "--scheme-id", "1", "--config-path", str(path)])
    assert result.exit_code == code, result.output
    assert all((current_output(root) / file).is_file() for file in OUTPUT_FILES)


def test_missing_scheme_missing_output_and_required_fields(repository):
    root, path, _ = repository
    with pytest.raises(ValueError, match="Choose a harmonization scheme"):
        run(root)
    with pytest.raises(ValueError, match="not found"):
        run(root, 999)
    with connect(root / "nap_tool.sqlite") as db:
        manifest = db.execute("SELECT source_manifest_hash FROM harmonize_set_output").fetchone()[0]
        db.execute("DELETE FROM harmonize_set_output")
    with pytest.raises(ValueError, match="no output"):
        run(root, 1)
    path.write_text("dso_slug\ntest\n", encoding="utf-8")
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO harmonize_set_output VALUES (1,1,?,?,?,'now')",
            (str(path.relative_to(root)), sha256_file(path), manifest),
        )
    with pytest.raises(ValueError, match="Missing required input fields"):
        run(root, 1)


def test_ui_run_preview_filters_and_download(repository):
    root, _, _ = repository
    with TestClient(create_app(root)) as client:
        assert client.get("/ui/classify").status_code == 200
        assert client.get("/api/classify/schemes/1").json()["has_output"] is False
        assert client.post("/api/classify/schemes/1/run").status_code == 200
        status = client.get("/api/classify/schemes/1").json()
        assert status["has_output"] is True
        assert status["report"]["metrics"][0]["expected"] == "80–90"
        assert (
            "Expected value (pass criteria)"
            in client.get("/api/classify/schemes/1/download/validation_report.md").text
        )
        preview = client.get("/api/classify/schemes/1/preview?asset_type=cable").json()
        assert preview["total_rows"] == 1
        assert (
            client.get("/api/classify/schemes/1/preview?asset_type=substation").json()["total_rows"]
            == 0
        )
        assert client.get("/api/classify/schemes/1/preview?view=unmapped").json()["total_rows"] == 0
        for file in OUTPUT_FILES:
            assert client.get("/api/classify/schemes/1/download/" + file).status_code == 200
        assert client.get("/api/classify/schemes/1/download/secret.txt").status_code == 404
        (current_output(root) / "classified.csv").write_text("corrupt", encoding="utf-8")
        assert client.get("/api/classify/schemes/1/preview").status_code == 409


@pytest.mark.parametrize("changed_config", [False, True])
def test_legacy_report_expected_values_do_not_modify_saved_results(
    repository, tmp_path, changed_config
):
    root, _, _ = repository
    run(root, 1)
    directory = current_output(root)
    report_path = directory / "validation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for item in report["metrics"]:
        del item["expected"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hashes"]["validation_report.json"] = sha256_file(report_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    config_path = Path("config/classify.yaml")
    if changed_config:
        settings = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        settings["validation"]["dso_count"]["pass"] = [81, 91]
        config_path = tmp_path / "changed-classify.yaml"
        config_path.write_text(yaml.safe_dump(settings), encoding="utf-8")

    status = output_status(root, 1, config_path=config_path)
    assert status["stale"] is changed_config
    assert status["report"]["expected_values_source"] == "current_configuration"
    assert status["report"]["metrics"][0]["expected"] == ("81–91" if changed_config else "80–90")
    assert [
        {key: value for key, value in item.items() if key != "expected"}
        for item in status["report"]["metrics"]
    ] == report["metrics"]
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_saved_expected_values_keep_original_criteria_after_config_changes(repository, tmp_path):
    root, _, _ = repository
    run(root, 1)
    settings = yaml.safe_load(Path("config/classify.yaml").read_text(encoding="utf-8"))
    settings["validation"]["dso_count"]["pass"] = [81, 91]
    config_path = tmp_path / "changed-classify.yaml"
    config_path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    status = output_status(root, 1, config_path=config_path)
    assert status["stale"] is True
    assert status["report"]["metrics"][0]["expected"] == "80–90"
    assert "expected_values_source" not in status["report"]


def test_invalid_configuration_produces_clear_cli_error(repository, monkeypatch, tmp_path):
    root, _, _ = repository
    monkeypatch.setenv("NAP_DATA_DIR", str(root))
    path = tmp_path / "bad.yaml"
    path.write_text("round: [broken", encoding="utf-8")
    result = CliRunner().invoke(app, ["classify", "--scheme-id", "1", "--config-path", str(path)])
    assert result.exit_code == 1
    assert "Invalid classification YAML" in result.output
    config = yaml.safe_load(Path("config/classify.yaml").read_text(encoding="utf-8"))
    config["locations"]["object_ref_pattern"] = "["
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    result = CliRunner().invoke(app, ["classify", "--scheme-id", "1", "--config-path", str(path)])
    assert result.exit_code == 1
    assert "Invalid classification regex" in result.output


def test_busy_run_is_rejected_without_changing_outputs(repository):
    root, _, _ = repository
    run(root, 1)
    before = (current_output(root) / "classified.csv").read_bytes()
    with FileLock(root / "classified/set_1/.scheme_1.lock", timeout=0):
        with pytest.raises(ValueError, match="already running"):
            run(root, 1)
    assert (current_output(root) / "classified.csv").read_bytes() == before


@pytest.mark.parametrize("content", ["../../nap_tool.sqlite", "garbage"])
def test_malformed_pointer_is_refused(repository, content):
    root, _, _ = repository
    run(root, 1)
    (root / "classified/set_1/scheme_1.current").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed classification pointer"):
        output_status(root, 1)


def test_selected_sets_have_separate_results_and_downloads(repository):
    root, source, original = repository
    second = source.with_name("second.csv")
    with second.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(original))
        writer.writeheader()
        writer.writerow({**original, "Maßnahme": "Neubau UW Second"})
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO harmonize_set(id,name,slug,table_type_id,created_at) "
            "VALUES (2,'Set two','two',1,'now')"
        )
        db.execute(
            "INSERT INTO harmonize_set_output(set_id,scheme_id,output_path,output_hash,"
            "source_manifest_hash,generated_at) "
            "VALUES (2,1,?,?,'fixture','now')",
            (str(second.relative_to(root)), sha256_file(second)),
        )
        db.execute(
            "UPDATE harmonize_set_output SET source_manifest_hash="
            "(SELECT source_manifest_hash FROM harmonize_set_output "
            "WHERE set_id=1 AND scheme_id=1) "
            "WHERE set_id=2 AND scheme_id=1"
        )
    with TestClient(create_app(root)) as client:
        assert client.post("/api/classify/schemes/1/run?set_id=1").status_code == 200
        before = (current_output(root) / "classified.csv").read_bytes()
        assert not client.get("/api/classify/schemes/1?set_id=2").json()["has_output"]
        assert client.get("/api/classify/schemes/1/preview?set_id=2").status_code == 404
        assert client.post("/api/classify/schemes/1/run?set_id=2").status_code == 200
        for set_id, name in [(1, "Neubau 20 kV Kabel"), (2, "Neubau UW Second")]:
            preview = client.get(f"/api/classify/schemes/1/preview?set_id={set_id}").json()
            assert preview["rows"][0][preview["header"].index("Maßnahme")] == name
            download = client.get(
                f"/api/classify/schemes/1/download/classified.csv?set_id={set_id}"
            )
            assert name in download.text
            assert not client.get(f"/api/classify/schemes/1?set_id={set_id}").json()["stale"]
        assert before == (current_output(root) / "classified.csv").read_bytes()
        assert client.post("/api/classify/schemes/1/run?set_id=999").status_code == 409


def test_classification_accepts_explicit_set_without_initial_set(repository):
    root, _, _ = repository
    with connect(root / "nap_tool.sqlite") as db:
        db.execute("UPDATE harmonize_scheme SET initial_set_id=NULL WHERE id=1")
    with TestClient(create_app(root)) as client:
        assert client.post("/api/classify/schemes/1/run").status_code == 409
        assert client.post("/api/classify/schemes/1/run?set_id=1").status_code == 200
        assert client.get("/api/classify/schemes/1?set_id=1").json()["has_output"]
        for suffix in ("", "/preview", "/download/classified.csv"):
            assert client.get(f"/api/classify/schemes/1{suffix}?set_id=999").status_code == 409
            assert client.get(f"/api/classify/schemes/1{suffix}").status_code == 409


def test_classification_scheme_outputs_are_independent(repository):
    root, _, _ = repository
    run(root, 1, set_id=1)
    first = (current_output(root) / "classified.csv").read_bytes()
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO harmonize_scheme(id,name,slug,initial_set_id,created_at,updated_at) "
            "VALUES (2,'Second','second',1,'now','now')"
        )
        db.execute(
            "INSERT INTO harmonize_field(scheme_id,field_key,title,position,created_at,updated_at) "
            "SELECT 2,field_key,title,position,created_at,updated_at "
            "FROM harmonize_field WHERE scheme_id=1"
        )
        db.execute(
            "INSERT INTO harmonize_set_output SELECT set_id,2,output_path,output_hash,"
            "source_manifest_hash,generated_at FROM harmonize_set_output WHERE scheme_id=1"
        )
    run(root, 2, set_id=1)
    assert (current_output(root) / "classified.csv").read_bytes() == first
    assert (current_output(root, 2) / "classified.csv").is_file()
    assert not output_status(root, 1, set_id=1)["stale"]
    assert not output_status(root, 2, set_id=1)["stale"]
    manifest_path = current_output(root, 2) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["set_id"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with TestClient(create_app(root)) as client:
        response = client.get("/api/classify/schemes/2/preview?set_id=1")
        assert response.status_code == 409
        assert "different set or scheme" in response.json()["detail"]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("", [("grid_level", "Irgendwo"), ("project_status", "Unklar")]),
        ("&field=project_status", [("project_status", "Unklar")]),
        ("&value=IRGEND", [("grid_level", "Irgendwo")]),
        ("&dso=test", [("project_status", "Unklar")]),
        ("&dso=other", [("grid_level", "Irgendwo"), ("project_status", "Unklar")]),
        ("&field=grid_level&dso=test", []),
    ],
)
def test_unmapped_preview_filters_by_header_columns(repository, query, expected):
    root, source, original = repository
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(original))
        writer.writeheader()
        writer.writerow({**original, "project_status": "Unklar"})
        writer.writerow(
            {**original, "dso_slug": "other", "project_status": "Unklar", "grid_level": "Irgendwo"}
        )
    with connect(root / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO dso(name,slug,mastr_nr,bdew_code,created_at,updated_at) "
            "VALUES ('Other','other','DEF','456','now','now')"
        )
        db.execute("UPDATE harmonize_set_output SET output_hash=?", (sha256_file(source),))
    run(root, 1)
    with TestClient(create_app(root)) as client:
        preview = client.get(f"/api/classify/schemes/1/preview?view=unmapped{query}").json()
    assert preview["options"]["field"] == ["grid_level", "project_status"]
    assert preview["options"]["dso"] == ["other", "test"]
    assert [(row[0], row[1]) for row in preview["rows"]] == expected
    assert preview["total_rows"] == len(expected)


def test_dso_slug_is_preserved_and_used_by_preview_filter(repository):
    from nap_tool.classifier.service import inputs, load_rows

    root, _, _ = repository
    rows, headers, mapping = load_rows(inputs(root, 1, set_id=1))
    assert "dso_slug" in headers
    assert mapping["dso_slug"] == "dso_slug"
    assert rows[0]["dso_slug"] == "test"
    run(root, 1, set_id=1)
    with TestClient(create_app(root)) as client:
        preview = client.get("/api/classify/schemes/1/preview?set_id=1&dso=test").json()
        assert preview["total_rows"] == 1
        assert preview["options"]["dso"] == ["test"]
        assert preview["rows"][0][preview["header"].index("dso_slug")] == "test"
        assert (
            client.get("/api/classify/schemes/1/preview?set_id=1&dso=missing").json()["total_rows"]
            == 0
        )


@pytest.mark.parametrize(
    ("type_name", "status"),
    [
        ("Maßnahmentabelle 2026", 200),
        ("maßnahmentabelle 2027", 200),
        ("Regionale Szenarioparameter 2026", 409),
    ],
)
def test_classification_accepts_year_specific_grid_measure_types(
    repository: tuple[Path, Path, dict[str, str]], type_name: str, status: int
) -> None:
    root, _, _ = repository
    with connect(root / "nap_tool.sqlite") as db:
        type_id = db.execute(
            "INSERT INTO table_type(name) VALUES (?) RETURNING id", (type_name,)
        ).fetchone()[0]
        db.execute("UPDATE harmonize_set SET table_type_id=? WHERE id=1", (type_id,))
    with TestClient(create_app(root)) as client:
        assert client.post("/api/classify/schemes/1/run?set_id=1").status_code == status


def test_year_config_path_prefers_single_year_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/classify_2026.yaml").write_text("round: {}\n", encoding="utf-8")
    explicit = Path("other/classify.yaml")
    assert year_config_path(CONFIG_PATH, [2026]) == CONFIG_PATH.with_name("classify_2026.yaml")
    assert year_config_path(CONFIG_PATH, [2024]) == CONFIG_PATH
    assert year_config_path(CONFIG_PATH, []) == CONFIG_PATH
    assert year_config_path(CONFIG_PATH, [2024, 2026]) == CONFIG_PATH
    assert year_config_path(explicit, [2026]) == explicit
