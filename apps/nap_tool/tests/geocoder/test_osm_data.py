# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Overpass query, parsing and storage of OSM grid objects."""

import json
import urllib.error
from pathlib import Path

import pytest

from nap_tool.geocoder.config import OsmSettings
from nap_tool.geocoder.osm_data import (
    fetch,
    load,
    overpass_query,
    parse_objects,
    post_query,
)

SETTINGS = OsmSettings(classes=["substation", "plant"])
EXPORT = json.dumps(
    {
        "osm3s": {"timestamp_osm_base": "2026-11-24T08:00:00Z"},
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 50.73,
                "lon": 13.4,
                "tags": {
                    "power": "substation",
                    "name": "Umspannwerk Musterdorf",
                    "operator": "Musternetz",
                    "voltage": "110000",
                },
            },
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 51.0, "lon": 13.0},
                "tags": {"power": "plant", "name": "Kraftwerk Beispiel"},
            },
            {"type": "node", "id": 3, "lat": 51.1, "lon": 13.1, "tags": {"power": "substation"}},
            {
                "type": "node",
                "id": 4,
                "lat": 51.2,
                "lon": 13.2,
                "tags": {"power": "generator", "name": "Windrad"},
            },
        ],
    }
).encode()


def test_query_names_the_classes_and_germany() -> None:
    query = overpass_query(["substation", "plant"])
    assert "^(substation|plant)$" in query and 'ISO3166-1"="DE"' in query
    assert "out center tags" in query


def test_parse_keeps_named_objects_of_the_configured_classes() -> None:
    objects, unnamed, status = parse_objects(EXPORT, ["substation", "plant"])
    assert [(o.id, o.cls, o.name) for o in objects] == [
        ("node/1", "substation", "Umspannwerk Musterdorf"),
        ("way/2", "plant", "Kraftwerk Beispiel"),
    ]
    assert (objects[0].operator, objects[0].voltage) == ("Musternetz", "110000")
    assert (objects[1].lat, objects[1].lon) == (51.0, 13.0)  # centre of a way
    assert (unnamed, status) == (1, "2026-11-24T08:00:00Z")


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"<html>busy</html>", "not valid JSON"), (b"{}", "no elements")],
)
def test_parse_rejects_bad_answers(content: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_objects(content, ["substation"])


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x.test", code, "busy", {}, None)


def test_post_retries_busy_server_with_backoff() -> None:
    answers = [http_error(502), http_error(429), b"ok"]
    pauses: list[float] = []

    def send(request) -> bytes:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert post_query("https://x.test", "q", send=send, sleep=pauses.append) == b"ok"
    assert pauses == [30, 60]


def test_post_gives_up_with_a_clear_error() -> None:
    def send(request) -> bytes:
        raise http_error(502)

    with pytest.raises(RuntimeError, match="Overpass"):
        post_query("https://x.test", "q", send=send, sleep=lambda s: None, attempts=2)


def test_post_does_not_retry_client_errors() -> None:
    calls: list[int] = []

    def send(request) -> bytes:
        calls.append(1)
        raise http_error(400)

    with pytest.raises(RuntimeError, match="400"):
        post_query("https://x.test", "q", send=send, sleep=lambda s: None)
    assert calls == [1]


def test_fetch_writes_version_and_pointer(tmp_path: Path) -> None:
    result = fetch(tmp_path, SETTINGS, content=EXPORT)
    assert (result.changed, result.objects, result.unnamed, result.repaired) == (True, 2, 1, False)
    data = load(tmp_path)
    assert data.version == result.version and len(data.objects) == 2
    manifest = data.manifest
    assert manifest["data_status"] == "2026-11-24T08:00:00Z"
    assert manifest["classes"] == ["substation", "plant"]
    assert (
        "OpenStreetMap contributors" in manifest["attribution"]
        and "ODbL" in manifest["attribution"]
    )


def test_fetch_downloads_when_no_content_is_given(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    result = fetch(tmp_path, SETTINGS, post=lambda url, query: calls.append((url, query)) or EXPORT)
    assert result.changed and calls[0][0] == SETTINGS.overpass_url and "power" in calls[0][1]


def test_unchanged_repaired_and_forced(tmp_path: Path) -> None:
    first = fetch(tmp_path, SETTINGS, content=EXPORT)
    again = fetch(tmp_path, SETTINGS, content=EXPORT)
    assert (again.version, again.changed, again.repaired) == (first.version, False, False)
    objects = tmp_path / "place_data/osm_objects" / first.version / "objects.csv"
    objects.write_text(objects.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    repaired = fetch(tmp_path, SETTINGS, content=EXPORT)
    assert (repaired.changed, repaired.repaired) == (True, True)
    assert load(tmp_path).objects
    forced = fetch(tmp_path, SETTINGS, content=EXPORT, force=True)
    assert (forced.changed, forced.repaired) == (True, False)


def test_load_without_data_is_none(tmp_path: Path) -> None:
    assert load(tmp_path) is None


def test_load_without_objects_still_checks_the_hash(tmp_path: Path) -> None:
    result = fetch(tmp_path, SETTINGS, content=EXPORT)
    assert load(tmp_path, with_objects=False).objects == []
    path = tmp_path / "place_data/osm_objects" / result.version / "objects.csv"
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing or modified"):
        load(tmp_path, with_objects=False)


def test_fetch_without_named_objects_is_refused(tmp_path: Path) -> None:
    empty = json.dumps({"elements": []}).encode()
    with pytest.raises(ValueError, match="no named objects"):
        fetch(tmp_path, SETTINGS, content=empty)


SUBSTATION = {
    "type": "node",
    "id": 1,
    "lat": 50.73,
    "lon": 13.4,
    "tags": {"power": "substation", "name": "Umspannwerk Musterdorf"},
}


def test_parse_rejects_overpass_remark_without_elements() -> None:
    content = json.dumps({"elements": [], "remark": "runtime error: Query timed out"}).encode()
    with pytest.raises(ValueError, match="Overpass reported"):
        parse_objects(content, ["substation"])


def test_truncated_export_with_remark_writes_nothing(tmp_path: Path) -> None:
    content = json.dumps(
        {"elements": [SUBSTATION], "remark": "runtime error: Query ran out of memory"}
    ).encode()
    with pytest.raises(ValueError, match="Overpass reported"):
        fetch(tmp_path, SETTINGS, content=content)
    assert not (tmp_path / "place_data/osm_objects.current").exists()
    assert not (tmp_path / "place_data/osm_objects").exists()


def test_post_requires_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="attempts must be at least 1"):
        post_query("https://x.test", "q", send=lambda r: b"", attempts=0)


def test_parse_rejects_invalid_element() -> None:
    with pytest.raises(ValueError, match="invalid element"):
        parse_objects(json.dumps({"elements": [1]}).encode(), ["substation"])


def test_malformed_pointer_does_not_block_fetch(tmp_path: Path) -> None:
    pointer = tmp_path / "place_data/osm_objects.current"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("garbage", encoding="utf-8")
    result = fetch(tmp_path, SETTINGS, content=EXPORT)
    assert result.changed
    assert load(tmp_path).version == result.version


def test_fetch_rebuilds_after_class_change(tmp_path: Path) -> None:
    first = fetch(tmp_path, SETTINGS, content=EXPORT)
    again = fetch(tmp_path, OsmSettings(classes=["substation"]), content=EXPORT)
    assert (again.version, again.changed, again.repaired) == (first.version, True, False)
    assert again.objects == 1
    assert load(tmp_path).manifest["classes"] == ["substation"]
