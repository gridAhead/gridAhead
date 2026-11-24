# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Download, build and load of the offline place data."""

import http.client
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from nap_tool.geocoder.config import load_config
from nap_tool.geocoder.place_data import fetch, is_ignored, load, parse_places

SETTINGS = load_config().place_data


def test_parse_keeps_settlements_and_converts(archive: bytes) -> None:
    places, status = parse_places(archive, SETTINGS)
    assert status == "31.12.2024"
    assert [place.name for place in places] == [
        "Musterdorf",
        "Beispielstadt",
        "Probstheim",
        "Kirchberg",
        "Kirchberg",
    ]
    musterdorf = places[0]
    assert (musterdorf.lat, musterdorf.lon) == (50.721709, 13.395888)
    assert (musterdorf.ags, musterdorf.population) == ("14522001", 500)
    assert places[1].population == 9000  # EWZ of a municipality


def test_parse_reports_missing_columns(make_archive) -> None:
    header = "NNID;OBA;NAME;AGS;RECHTS"
    with pytest.raises(ValueError, match="NAME2, EWZ, EWZ_GER, HOCH"):
        parse_places(make_archive([], header), SETTINGS)


def test_parse_reports_missing_member(archive: bytes) -> None:
    settings = SETTINGS.model_copy(update={"member": "gn250/OTHER.csv"})
    with pytest.raises(ValueError, match="lacks gn250/OTHER.csv"):
        parse_places(archive, settings)


def test_fetch_writes_version_and_pointer(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert (result.changed, result.places) == (True, 5)
    directory = tmp_path / "place_data" / "gn250" / result.version
    assert (directory / "source.zip").read_bytes() == archive
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["url"] == SETTINGS.url
    assert manifest["data_status"] == "31.12.2024"
    attribution = manifest["attribution"]
    assert attribution.startswith("© BKG (") and "dl-de/by-2-0" in attribution
    assert "Datenquellen: https://sgx.geodatenzentrum.de/" in attribution
    assert "Daten verändert" in attribution
    pointer = tmp_path / "place_data" / "gn250.current"
    assert pointer.read_text(encoding="utf-8") == result.version
    place_data = load(tmp_path)
    assert place_data.version == result.version
    assert len(place_data.places) == 5


def test_fetch_same_download_is_unchanged_unless_forced(tmp_path: Path, archive: bytes) -> None:
    first = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    again = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    forced = fetch(tmp_path, SETTINGS, force=True, read=lambda url: archive)
    assert (again.version, again.changed, again.places) == (first.version, False, 5)
    assert forced.changed and not forced.repaired


def test_fetch_download_error(tmp_path: Path) -> None:
    def failing(url: str) -> bytes:
        raise OSError("offline")

    with pytest.raises(RuntimeError, match="Failed to download"):
        fetch(tmp_path, SETTINGS, read=failing)


def test_load_without_place_data(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nap-tool place-data fetch"):
        load(tmp_path)


def test_load_detects_modified_places(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    places = tmp_path / "place_data" / "gn250" / result.version / "places.csv"
    places.write_text(places.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing or modified"):
        load(tmp_path)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_is_ignored(tmp_path: Path) -> None:
    assert is_ignored(tmp_path) is None  # not a repository
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert is_ignored(tmp_path) is False
    (tmp_path / ".gitignore").write_text("place_data/\n", encoding="utf-8")
    assert is_ignored(tmp_path) is True


def test_parse_rejects_non_zip() -> None:
    with pytest.raises(ValueError, match="not a valid ZIP"):
        parse_places(b"<html>error</html>", SETTINGS)


def test_fetch_non_zip_keeps_current_version(tmp_path: Path, archive: bytes) -> None:
    good = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    with pytest.raises(ValueError, match="not a valid ZIP"):
        fetch(tmp_path, SETTINGS, read=lambda url: b"<html>error</html>")
    assert load(tmp_path).version == good.version


def test_fetch_http_exception_is_runtime_error(tmp_path: Path) -> None:
    def failing(url: str) -> bytes:
        raise http.client.IncompleteRead(b"")

    with pytest.raises(RuntimeError, match="Failed to download"):
        fetch(tmp_path, SETTINGS, read=failing)


def test_fetch_repairs_damaged_current_version(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert not result.repaired
    directory = tmp_path / "place_data" / "gn250" / result.version
    (directory / "places.csv").write_text("broken\n", encoding="utf-8")
    repaired = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert (repaired.version, repaired.changed, repaired.repaired) == (result.version, True, True)
    assert len(load(tmp_path).places) == 5
    (directory / "manifest.json").unlink()
    assert fetch(tmp_path, SETTINGS, read=lambda url: archive).changed
    assert len(load(tmp_path).places) == 5
    assert not [path for path in directory.iterdir() if path.name.endswith(".tmp")]


def test_fetch_repairs_missing_or_modified_source_zip(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    source = tmp_path / "place_data" / "gn250" / result.version / "source.zip"
    source.unlink()
    repaired = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert (repaired.changed, repaired.repaired) == (True, True)
    assert source.read_bytes() == archive
    source.write_bytes(b"modified")
    repaired = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert (repaired.changed, repaired.repaired) == (True, True)
    assert source.read_bytes() == archive
    assert not fetch(tmp_path, SETTINGS, read=lambda url: archive).changed


def test_unchanged_fetch_keeps_manifest(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    path = tmp_path / "place_data" / "gn250" / result.version / "manifest.json"
    before = path.read_bytes()
    fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert path.read_bytes() == before


def test_parse_reports_malformed_row(make_archive) -> None:
    record = {"NNID": "DEBKGGND0000BAD", "OBA": "AX_Ortslage", "NAME": "X", "HOCH": "5600000"}
    with pytest.raises(ValueError, match="DEBKGGND0000BAD"):
        parse_places(make_archive([record]), SETTINGS)
    record = {**record, "RECHTS": "nan"}
    with pytest.raises(ValueError, match="DEBKGGND0000BAD"):
        parse_places(make_archive([record]), SETTINGS)


def test_parse_population_defaults_to_zero(make_archive) -> None:
    record = {
        "NNID": "N1",
        "OBA": "AX_Ortslage",
        "NAME": "X",
        "RECHTS": "500000",
        "HOCH": "5600000",
    }
    places, _ = parse_places(make_archive([record]), SETTINGS)
    assert places[0].population == 0


def test_fetch_rejects_archive_without_places(tmp_path: Path, make_archive) -> None:
    with pytest.raises(ValueError, match="no places"):
        fetch(tmp_path, SETTINGS, read=lambda url: make_archive([]))


def test_load_rejects_malformed_pointer(tmp_path: Path) -> None:
    pointer = tmp_path / "place_data" / "gn250.current"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("../evil", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed place data pointer"):
        load(tmp_path)


def test_load_rejects_unusable_manifest(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    path = tmp_path / "place_data" / "gn250" / result.version / "manifest.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Malformed place data manifest"):
        load(tmp_path)


@pytest.mark.network
def test_live_gn250_builds(tmp_path: Path) -> None:
    """Downloads the real GN250 (~18 MB); run with `pytest -m network`."""
    result = fetch(tmp_path, SETTINGS)
    place_data = load(tmp_path)
    assert result.places > 50000
    berlin = [
        place
        for place in place_data.places
        if place.name == "Berlin" and place.object_class == "AX_Gemeinde"
    ]
    assert berlin and 52.3 < berlin[0].lat < 52.7 and 13.0 < berlin[0].lon < 13.8


def test_load_without_places_still_verifies_hash(tmp_path: Path, archive: bytes) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert load(tmp_path, with_places=False).places == []
    places = tmp_path / "place_data" / "gn250" / result.version / "places.csv"
    places.write_text(places.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing or modified"):
        load(tmp_path, with_places=False)


def test_load_distinguishes_unreadable_from_malformed_manifest(
    tmp_path: Path, archive: bytes
) -> None:
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    path = tmp_path / "place_data" / "gn250" / result.version / "manifest.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Malformed place data manifest"):
        load(tmp_path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing or modified place data manifest"):
        load(tmp_path)


def test_fetch_rebuilds_after_object_class_change(tmp_path: Path, archive: bytes) -> None:
    first = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    narrow = SETTINGS.model_copy(update={"object_classes": ["AX_Gemeinde"]})
    again = fetch(tmp_path, narrow, read=lambda url: archive)
    assert (again.version, again.changed, again.repaired) == (first.version, True, False)
    assert again.places == 1
    assert load(tmp_path).manifest["object_classes"] == ["AX_Gemeinde"]


def test_malformed_pointer_does_not_block_fetch(tmp_path: Path, archive: bytes) -> None:
    pointer = tmp_path / "place_data" / "gn250.current"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("garbage", encoding="utf-8")
    result = fetch(tmp_path, SETTINGS, read=lambda url: archive)
    assert result.changed
    assert load(tmp_path).version == result.version
