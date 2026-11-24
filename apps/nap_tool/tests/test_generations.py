# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable output generations behind a pointer file."""

from pathlib import Path

import pytest
from filelock import FileLock

from nap_tool.generations import (
    VERSIONS_DIR,
    publish_generation,
    published_directory,
    scheme_lock,
    write_pointer,
)


def test_write_pointer_replaces_content(tmp_path: Path) -> None:
    pointer = tmp_path / "sub" / "x.current"
    write_pointer(pointer, "first")
    write_pointer(pointer, "second")
    assert pointer.read_text(encoding="utf-8") == "second"
    assert [path.name for path in pointer.parent.iterdir()] == ["x.current"]


def test_publish_generation_switches_pointer(tmp_path: Path) -> None:
    directory = publish_generation(tmp_path, 3, {"a.txt": b"A"}, lambda: None)
    assert published_directory(tmp_path, 3) == directory
    assert (directory / "a.txt").read_bytes() == b"A"


def test_failed_check_keeps_previous_generation(tmp_path: Path) -> None:
    first = publish_generation(tmp_path, 3, {"a.txt": b"A"}, lambda: None)

    def changed() -> None:
        raise ValueError("Input changed")

    with pytest.raises(ValueError, match="Input changed"):
        publish_generation(tmp_path, 3, {"a.txt": b"B"}, changed)
    assert published_directory(tmp_path, 3) == first
    assert [path.name for path in (tmp_path / VERSIONS_DIR).iterdir()] == [first.name]


def test_scheme_lock_rejects_second_holder(tmp_path: Path) -> None:
    with FileLock(tmp_path / ".scheme_3.lock", timeout=0):
        with pytest.raises(ValueError, match="busy"):
            with scheme_lock(tmp_path, 3, "busy"):
                pass
