# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Hash-named data versions behind a pointer file."""

import json
from pathlib import Path

import pytest

from nap_tool.geocoder.versioned_data import VersionedSource

SOURCE = VersionedSource(
    directory="place_data",
    name="src",
    label="test data",
    manifest_keys=("a", "b"),
    classes_key="b",
    source_file="source.bin",
    lookup_file="lookup.csv",
)


def build(content: bytes) -> tuple[bytes, dict]:
    """Lookup = the content reversed; manifest entries a and b."""
    return content[::-1], {"a": 1, "b": ["x", "y"]}


def write_pointer(root: Path, text: str) -> None:
    (root / "place_data").mkdir(exist_ok=True)
    (root / "place_data/src.current").write_text(text, encoding="utf-8")


def test_no_pointer_means_no_version(tmp_path: Path) -> None:
    assert SOURCE.current_version(tmp_path) is None
    assert SOURCE.usable_version(tmp_path) is None
    assert SOURCE.load_current(tmp_path) is None


def test_write_then_read(tmp_path: Path) -> None:
    manifest = {"a": 1, "b": 2}
    SOURCE.write(
        tmp_path, "abcdef01", {"x.csv": b"x", "manifest.json": json.dumps(manifest).encode()}
    )
    assert SOURCE.current_version(tmp_path) == "abcdef01"
    assert SOURCE.relative("abcdef01") == "place_data/src/abcdef01"
    assert (tmp_path / "place_data/src/abcdef01/x.csv").read_bytes() == b"x"
    assert SOURCE.manifest(tmp_path, "abcdef01") == manifest


def test_malformed_pointer(tmp_path: Path) -> None:
    write_pointer(tmp_path, "../evil")
    with pytest.raises(ValueError, match="Malformed test data pointer"):
        SOURCE.current_version(tmp_path)
    assert SOURCE.usable_version(tmp_path) is None


def test_unreadable_manifest(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Missing or modified test data manifest"):
        SOURCE.manifest(tmp_path, "abcdef01")


@pytest.mark.parametrize("content", [b"[]", b'{"a": 1}'])
def test_malformed_manifest(tmp_path: Path, content: bytes) -> None:
    folder = tmp_path / "place_data/src/abcdef01"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_bytes(content)
    with pytest.raises(RuntimeError, match="Malformed test data manifest"):
        SOURCE.manifest(tmp_path, "abcdef01")


def test_verified_rejects_a_modified_file(tmp_path: Path) -> None:
    SOURCE.write(tmp_path, "abcdef01", {"x.csv": b"x"})
    with pytest.raises(RuntimeError, match="Missing or modified"):
        SOURCE.verified(tmp_path, "abcdef01", "x.csv", "0" * 64)


def test_store_writes_files_and_hashes(tmp_path: Path) -> None:
    stored = SOURCE.store(tmp_path, b"abc", classes=["x", "y"], build=build)
    assert (stored.changed, stored.repaired) == (True, False)
    version, manifest, path = SOURCE.load_current(tmp_path)
    assert version == stored.version and manifest == stored.manifest
    assert path.read_bytes() == b"cba"
    assert set(manifest) == {"a", "b", "sha256", "lookup_sha256"}
    assert manifest["sha256"].startswith(version)


def test_store_keeps_an_intact_version_for_the_same_classes(tmp_path: Path) -> None:
    first = SOURCE.store(tmp_path, b"abc", classes=["x", "y"], build=build)
    again = SOURCE.store(tmp_path, b"abc", classes=["y", "x"], build=build)
    assert (again.version, again.changed, again.repaired) == (first.version, False, False)
    assert again.manifest == first.manifest


def test_store_rebuilds_for_other_classes_or_when_forced(tmp_path: Path) -> None:
    SOURCE.store(tmp_path, b"abc", classes=["x", "y"], build=build)
    other = SOURCE.store(tmp_path, b"abc", classes=["x"], build=build)
    forced = SOURCE.store(tmp_path, b"abc", classes=None, build=build)
    assert (other.changed, other.repaired) == (True, False)
    assert (forced.changed, forced.repaired) == (True, False)


@pytest.mark.parametrize("damaged", ["source.bin", "lookup.csv", "manifest.json"])
def test_store_repairs_a_damaged_version(tmp_path: Path, damaged: str) -> None:
    first = SOURCE.store(tmp_path, b"abc", classes=["x", "y"], build=build)
    (tmp_path / SOURCE.relative(first.version) / damaged).write_bytes(b"broken")
    repaired = SOURCE.store(tmp_path, b"abc", classes=["x", "y"], build=build)
    assert (repaired.changed, repaired.repaired) == (True, True)
    assert SOURCE.load_current(tmp_path)[2].read_bytes() == b"cba"


def test_store_overwrites_a_malformed_pointer(tmp_path: Path) -> None:
    write_pointer(tmp_path, "garbage")
    stored = SOURCE.store(tmp_path, b"abc", classes=["x", "y"], build=build)
    assert stored.changed and SOURCE.current_version(tmp_path) == stored.version


def test_rejected_build_writes_nothing(tmp_path: Path) -> None:
    def reject(content: bytes) -> tuple[bytes, dict]:
        raise ValueError("bad download")

    with pytest.raises(ValueError, match="bad download"):
        SOURCE.store(tmp_path, b"abc", classes=["x"], build=reject)
    assert not (tmp_path / "place_data").exists()
