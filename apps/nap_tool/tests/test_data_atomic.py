# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the atomic file write."""

from __future__ import annotations

from pathlib import Path

import pytest

from nap_tool import data
from nap_tool.data import atomic_write_bytes


def test_replaces_content_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert [path.name for path in tmp_path.iterdir()] == ["file.txt"]


def test_cleans_up_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(source: Path, destination: Path) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(data, "replace_file", fail)
    target = tmp_path / "file.txt"
    target.write_bytes(b"old")
    with pytest.raises(PermissionError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert [path.name for path in tmp_path.iterdir()] == ["file.txt"]
