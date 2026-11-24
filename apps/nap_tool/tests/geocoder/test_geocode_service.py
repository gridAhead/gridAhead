# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Geocoding of a real classification output in a temporary data repository."""

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml
from filelock import FileLock
from typer.testing import CliRunner

from nap_tool.classifier.config import load_config as load_classify_config
from nap_tool.classifier.service import run as classify
from nap_tool.cli import app
from nap_tool.data import sha256_file
from nap_tool.database.schema import connect
from nap_tool.generations import published_directory
from nap_tool.geocoder.config import CONFIG_PATH, load_config
from nap_tool.geocoder.osm_data import fetch as osm_fetch
from nap_tool.geocoder.place_data import fetch
from nap_tool.geocoder.service import OUTPUT_FILES, output_status, run

MEASURES = [
    "Neubau UW Musterdorf",
    "Neubau 110-kV-Kabel Musterdorf - Beispielstadt",
    "Netzausbau Probstheim",
    "Netzausbau Kirchberg",
    "Netzverstärkung Musterdorf Nord",
    "Netzausbau Nirgendwo",
    "Sammler Kleinstmaßnahmen MS",
]


def current(root: Path) -> Path:
    return published_directory(root / "geocoded/set_1", 1)


@pytest.fixture
def repository(tmp_path: Path, archive: bytes) -> Path:
    headers = list(load_classify_config().required_fields)
    path = tmp_path / "harmonized/scheme_1/output.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, headers)
        writer.writeheader()
        for number, name in enumerate(MEASURES, start=2):
            values = dict.fromkeys(headers, "")
            values.update(
                dso_slug="test", measure_no=str(number), measure_name=name, grid_level="MS"
            )
            values["source_cells_json"] = json.dumps(
                {
                    "origin": {
                        "extract_table_id": 1,
                        "row_number": number,
                        "document_id": 1,
                        "currentFrom": "2024-04-01",
                        "clean_is_confirmed": True,
                    },
                    "sources": [],
                }
            )
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
            "VALUES (1,'measure_name','measure_name',1,'now','now')"
        )
        from nap_tool.ui.harmonize_api import _fields, _pair_manifest, _pair_tables

        scheme = db.execute("SELECT * FROM harmonize_scheme WHERE id=1").fetchone()
        tables = _pair_tables(db, tmp_path, scheme, 1)
        manifest = _pair_manifest(_fields(db, scheme, tables), tables)
        db.execute(
            "INSERT INTO harmonize_set_output VALUES (1,1,?,?,?,'now')",
            (str(path.relative_to(tmp_path)), sha256_file(path), manifest),
        )
    classify(tmp_path, 1)
    fetch(tmp_path, load_config().place_data, read=lambda url: archive)
    return tmp_path


def geocoded_rows(root: Path) -> dict[str, dict[str, str]]:
    with (current(root) / "geocoded.csv").open(encoding="utf-8", newline="") as source:
        return {row["row_id"]: row for row in csv.DictReader(source)}


def test_run_publishes_generation(repository: Path) -> None:
    result = run(repository, 1)
    rows = geocoded_rows(repository)
    start, end = "inferred_location_start", "inferred_location_end"
    assert rows["1-2"][f"{start}_geocode"] == "exact+station"
    assert (rows["1-2"][f"{start}_lat"], rows["1-2"][f"{start}_lon"]) == (
        "50.721709",
        "13.395888",
    )
    assert rows["1-2"][f"{start}_match"] == "Musterdorf (14522001)"
    assert rows["1-3"][f"{end}_geocode"] == "exact"
    assert rows["1-3"][f"{end}_match"] == "Beispielstadt (14522002)"
    assert rows["1-4"][f"{start}_geocode"] == "exact"
    assert rows["1-5"][f"{start}_geocode"] == "nearest_to_anchor"
    assert rows["1-5"][f"{start}_match"] == "Kirchberg (14522004)"
    assert rows["1-6"][f"{start}_geocode"] == "strip_suffix"
    assert rows["1-7"][f"{start}_geocode"] == "unresolved:no_match"
    assert rows["1-8"][f"{start}_geocode"] == ""
    assert (result.report["locations"], result.report["resolved"]) == (7, 6)

    directory = current(repository)
    manifest = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
    for name in OUTPUT_FILES:
        assert sha256_file(directory / name) == manifest["hashes"][name]
    features = json.loads((directory / "geocoded.geojson").read_text(encoding="utf-8"))
    assert len(features["features"]) == 6
    assert "© BKG (" in (directory / "geocode_report.md").read_text(encoding="utf-8")
    unresolved = (directory / "unresolved_names.csv").read_text(encoding="utf-8")
    assert "Nirgendwo,place,no_match,1,test" in unresolved
    assert not output_status(repository, 1)["stale"]


def test_rerun_gives_identical_files(repository: Path) -> None:
    run(repository, 1)
    first = {name: (current(repository) / name).read_bytes() for name in OUTPUT_FILES}
    run(repository, 1)
    assert first == {name: (current(repository) / name).read_bytes() for name in OUTPUT_FILES}


def test_changed_config_makes_output_stale(repository: Path, tmp_path_factory) -> None:
    run(repository, 1)
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["matching"]["max_anchor_km"] = 50
    other = tmp_path_factory.mktemp("config") / "geocode.yaml"
    other.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert output_status(repository, 1, other)["stale"]


def test_stale_classification_is_refused(repository: Path) -> None:
    with connect(repository / "nap_tool.sqlite") as db:
        db.execute("UPDATE dso SET bdew_code='456'")
    with pytest.raises(ValueError, match="stale"):
        run(repository, 1)


def test_missing_place_data_is_refused(repository: Path) -> None:
    (repository / "place_data/gn250.current").unlink()
    with pytest.raises(ValueError, match="nap-tool place-data fetch"):
        run(repository, 1)


def test_failure_keeps_published_output(repository: Path) -> None:
    run(repository, 1)
    before = current(repository)
    version = (repository / "place_data/gn250.current").read_text(encoding="utf-8")
    places = repository / "place_data/gn250" / version / "places.csv"
    places.write_text(places.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing or modified"):
        run(repository, 1)
    assert current(repository) == before


def test_busy_run_is_rejected(repository: Path) -> None:
    run(repository, 1)
    with FileLock(repository / "geocoded/set_1/.scheme_1.lock", timeout=0):
        with pytest.raises(ValueError, match="already running"):
            run(repository, 1)


def test_cli_geocode(repository: Path) -> None:
    result = CliRunner().invoke(
        app, ["geocode", "--scheme-id", "1"], env={"NAP_DATA_DIR": str(repository)}
    )
    assert result.exit_code == 0, result.output
    assert "Resolved: 6 of 7 (85.7%)" in result.output
    assert "unresolved:no_match: 1" in result.output


def test_cli_geocode_error_exit(repository: Path) -> None:
    (repository / "place_data/gn250.current").unlink()
    result = CliRunner().invoke(
        app, ["geocode", "--scheme-id", "1"], env={"NAP_DATA_DIR": str(repository)}
    )
    assert result.exit_code == 1
    assert "nap-tool place-data fetch" in result.output


def test_cli_place_data_fetch(tmp_path: Path, archive: bytes, monkeypatch) -> None:
    from nap_tool.geocoder import place_data

    monkeypatch.setattr(place_data, "read_url", lambda url: archive)
    result = CliRunner().invoke(app, ["place-data", "fetch"], env={"NAP_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0, result.output
    assert "updated: 5 places" in result.output


def test_tampered_output_is_stale(repository: Path) -> None:
    run(repository, 1)
    csv_file = current(repository) / "geocoded.csv"
    csv_file.write_text(csv_file.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    status = output_status(repository, 1)
    assert status["has_output"] and status["stale"]
    assert "Missing or modified" in status["reason"]


def test_dangling_pointer_has_no_output(repository: Path) -> None:
    run(repository, 1)
    shutil.rmtree(current(repository))
    assert not output_status(repository, 1)["has_output"]


def test_no_output_status(repository: Path) -> None:
    assert output_status(repository, 1) == dict(has_output=False, stale=False, reason="")


def test_stale_message_names_default_configuration(repository: Path) -> None:
    with connect(repository / "nap_tool.sqlite") as db:
        db.execute("UPDATE dso SET bdew_code='456'")
    with pytest.raises(ValueError, match="nap-tool classify` with the default configuration"):
        run(repository, 1)


def test_malformed_place_data_manifest_is_runtime_error(repository: Path) -> None:
    version = (repository / "place_data/gn250.current").read_text(encoding="utf-8")
    manifest = repository / "place_data/gn250" / version / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    del data["attribution"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Malformed place data manifest"):
        run(repository, 1)


def test_malformed_output_manifest_is_stale(repository: Path) -> None:
    run(repository, 1)
    path = current(repository) / "run_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["fingerprint"]
    path.write_text(json.dumps(data), encoding="utf-8")
    status = output_status(repository, 1)
    assert status["has_output"] and status["stale"]
    assert "Malformed geocoding manifest" in status["reason"]


def test_object_class_order_is_irrelevant(repository: Path, tmp_path_factory) -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["place_data"]["object_classes"] = config["place_data"]["object_classes"][::-1]
    other = tmp_path_factory.mktemp("config") / "geocode.yaml"
    other.write_text(yaml.safe_dump(config), encoding="utf-8")
    run(repository, 1, other)


def test_object_class_drift_is_refused(repository: Path, tmp_path_factory) -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["place_data"]["object_classes"] = ["AX_Gemeinde"]
    other = tmp_path_factory.mktemp("config") / "geocode.yaml"
    other.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="place-data fetch"):
        run(repository, 1, other)


def test_input_change_during_run_keeps_published_output(
    repository: Path, archive: bytes, make_archive, monkeypatch
) -> None:
    from nap_tool.geocoder import service

    run(repository, 1)
    before = current(repository)
    real = service.geocode_rows

    def changing(*args, **kwargs):
        result = real(*args, **kwargs)
        other = make_archive(
            [
                {
                    "NNID": "X",
                    "OBA": "AX_Ortslage",
                    "NAME": "Neu",
                    "AGS": "1",
                    "RECHTS": "810000",
                    "HOCH": "5628000",
                }
            ]
        )
        fetch(repository, load_config().place_data, read=lambda url: other)
        return result

    monkeypatch.setattr(service, "geocode_rows", changing)
    with pytest.raises(ValueError, match="Input changed during geocoding"):
        run(repository, 1)
    assert current(repository) == before


def test_cli_unknown_set(repository: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["geocode", "--scheme-id", "1", "--set-id", "99"],
        env={"NAP_DATA_DIR": str(repository)},
    )
    assert result.exit_code == 1
    assert not (repository / "geocoded/set_99").exists()


def test_cli_place_data_fetch_unchanged_and_repaired(
    tmp_path: Path, archive: bytes, monkeypatch
) -> None:
    from nap_tool.geocoder import place_data

    monkeypatch.setattr(place_data, "read_url", lambda url: archive)
    env = {"NAP_DATA_DIR": str(tmp_path)}
    CliRunner().invoke(app, ["place-data", "fetch"], env=env)
    again = CliRunner().invoke(app, ["place-data", "fetch"], env=env)
    assert "unchanged: 5 places" in again.output
    version = (tmp_path / "place_data/gn250.current").read_text(encoding="utf-8")
    (tmp_path / "place_data/gn250" / version / "places.csv").write_text(
        "broken\n", encoding="utf-8"
    )
    repaired = CliRunner().invoke(app, ["place-data", "fetch"], env=env)
    assert "repaired: 5 places" in repaired.output


def test_run_parses_places_once(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nap_tool.geocoder import place_data

    original = place_data._read_places_csv
    calls: list[Path] = []

    def spy(path: Path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(place_data, "_read_places_csv", spy)
    run(repository, 1)
    assert len(calls) == 1
    assert output_status(repository, 1)["stale"] is False
    assert len(calls) == 1


def test_modified_places_are_detected_without_parsing(repository: Path) -> None:
    run(repository, 1)
    version = (repository / "place_data/gn250.current").read_text(encoding="utf-8")
    places = repository / "place_data/gn250" / version / "places.csv"
    places.write_text(places.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    status = output_status(repository, 1)
    assert status["stale"] and "Missing or modified" in status["reason"]
    with pytest.raises(RuntimeError, match="Missing or modified"):
        run(repository, 1)


OSM_EXPORT = json.dumps(
    {
        "osm3s": {"timestamp_osm_base": "2026-11-24T08:00:00Z"},
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 50.73,
                "lon": 13.4,
                "tags": {"power": "substation", "name": "Umspannwerk Musterdorf"},
            }
        ],
    }
).encode()


def test_osm_objects_upgrade_station_points(repository: Path) -> None:
    osm_fetch(repository, load_config().osm, content=OSM_EXPORT)
    result = run(repository, 1)
    rows = geocoded_rows(repository)
    start = "inferred_location_start"
    assert rows["1-2"][f"{start}_geocode"] == "osm_substation"
    assert rows["1-2"][f"{start}_precision"] == "object"
    assert (rows["1-2"][f"{start}_lat"], rows["1-2"][f"{start}_lon"]) == ("50.730000", "13.400000")
    assert rows["1-4"][f"{start}_precision"] == "settlement"
    assert result.report["osm"] == {"matched": 1, "rescued": 0}
    assert result.report["osm_objects"]["data_status"] == "2026-11-24T08:00:00Z"
    report = (current(repository) / "geocode_report.md").read_text(encoding="utf-8")
    assert "© OpenStreetMap contributors" in report


def test_osm_data_changes_the_fingerprint(repository: Path) -> None:
    run(repository, 1)
    assert not output_status(repository, 1)["stale"]
    osm_fetch(repository, load_config().osm, content=OSM_EXPORT)
    assert output_status(repository, 1)["stale"]


def test_osm_classes_must_match_the_configuration(repository: Path) -> None:
    narrow = load_config().osm.model_copy(update={"classes": ["substation"], "kinds": {}})
    osm_fetch(repository, narrow, content=OSM_EXPORT)
    with pytest.raises(ValueError, match="osm-fetch"):
        run(repository, 1)


def test_without_osm_data_the_report_has_no_osm_summary(repository: Path) -> None:
    result = run(repository, 1)
    assert result.report["osm_objects"] is None
    assert result.report["osm"] == {"matched": 0, "rescued": 0}


def test_cli_osm_fetch_from_file(tmp_path: Path) -> None:
    export = tmp_path / "export.json"
    export.write_bytes(OSM_EXPORT)
    env = {"NAP_DATA_DIR": str(tmp_path)}
    first = CliRunner().invoke(
        app, ["place-data", "osm-fetch", "--from-file", str(export)], env=env
    )
    assert first.exit_code == 0, first.output
    assert "updated: 1 objects" in first.output
    again = CliRunner().invoke(
        app, ["place-data", "osm-fetch", "--from-file", str(export)], env=env
    )
    assert "unchanged: 1 objects" in again.output


def test_cli_osm_fetch_reports_errors(tmp_path: Path) -> None:
    export = tmp_path / "export.json"
    export.write_bytes(b"<html>busy</html>")
    result = CliRunner().invoke(
        app,
        ["place-data", "osm-fetch", "--from-file", str(export)],
        env={"NAP_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 1
    assert "OSM data error" in result.output and "not valid JSON" in result.output


def test_cli_osm_fetch_missing_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["place-data", "osm-fetch", "--from-file", str(tmp_path / "none.json")],
        env={"NAP_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 1 and "OSM data error" in result.output
