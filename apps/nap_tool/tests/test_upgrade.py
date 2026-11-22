# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""`nap-tool upgrade`: explicit, rerunnable DB_VERSION upgrades of nap_data."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nap_tool.classifier.service import published_directory
from nap_tool.cli import app
from nap_tool.database.schema import DB_VERSION, connect
from nap_tool.database.upgrade import upgrade_repository

GENERATION = "scheme_1_" + "a" * 32


def _make_db(root: Path, version: int) -> Path:
    path = root / "nap_tool.sqlite"
    with connect(path):
        pass
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    return path


def _user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A DB_VERSION 20 repository with one generation and no `scheme_1` link yet."""
    _make_db(tmp_path, 20)
    generation = tmp_path / "classified/set_1/.versions" / GENERATION
    generation.mkdir(parents=True)
    (generation / "classified.csv").write_text("row_id\n1\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("kind", ["symlink", "git text file"])
def test_link_becomes_pointer(legacy: Path, kind: str) -> None:
    """A symlink, or the text file a checkout without symlink support makes of it."""
    set_directory = legacy / "classified/set_1"
    link = set_directory / "scheme_1"
    if kind == "symlink":
        try:
            link.symlink_to(Path(".versions") / GENERATION, target_is_directory=True)
        except OSError:
            pytest.skip("creating symlinks needs Developer Mode or admin rights on Windows")
    else:
        link.write_text(f".versions/{GENERATION}", encoding="utf-8")
    assert upgrade_repository(legacy) == [
        (20, {"classification_pointers": 1}),
        (21, {"document_columns_added": 0}),
        (22, {"document_columns_added": 0}),
        (23, {"markdown_artifacts": 0}),
    ]
    assert _user_version(legacy / "nap_tool.sqlite") == DB_VERSION
    assert not os.path.lexists(link)
    assert (published_directory(set_directory, 1) / "classified.csv").is_file()
    with connect(legacy / "nap_tool.sqlite"):
        pass


@pytest.mark.parametrize(
    "target,match",
    [
        (".versions/scheme_1_" + "b" * 32, "missing generation"),
        (f"../../{GENERATION}", "does not point into"),
    ],
)
def test_bad_link_keeps_old_version_and_can_be_rerun(legacy: Path, target: str, match: str):
    """A bad link stops the upgrade before the version changes; fixing it lets a rerun pass."""
    link = legacy / "classified/set_1/scheme_1"
    link.write_text(target, encoding="utf-8")
    with pytest.raises(RuntimeError, match=match):
        upgrade_repository(legacy)
    assert _user_version(legacy / "nap_tool.sqlite") == 20
    assert not (legacy / "classified/set_1/scheme_1.current").exists()
    link.write_text(f".versions/{GENERATION}", encoding="utf-8")
    assert upgrade_repository(legacy) == [
        (20, {"classification_pointers": 1}),
        (21, {"document_columns_added": 0}),
        (22, {"document_columns_added": 0}),
        (23, {"markdown_artifacts": 0}),
    ]


def test_repository_without_classification_output(legacy: Path) -> None:
    """Only the version changes when nothing was classified yet."""
    assert upgrade_repository(legacy) == [
        (20, {"classification_pointers": 0}),
        (21, {"document_columns_added": 0}),
        (22, {"document_columns_added": 0}),
        (23, {"markdown_artifacts": 0}),
    ]
    assert _user_version(legacy / "nap_tool.sqlite") == DB_VERSION


@pytest.mark.parametrize("version,hint", [(DB_VERSION + 1, "update nap_tool"), (5, "starts at")])
def test_unsupported_versions_are_refused(tmp_path: Path, version: int, hint: str) -> None:
    """A newer repository or one older than any upgrade step stays untouched."""
    path = _make_db(tmp_path, version)
    with pytest.raises(RuntimeError, match=hint):
        upgrade_repository(tmp_path)
    assert _user_version(path) == version


def test_connect_points_old_repository_to_upgrade(legacy: Path) -> None:
    """The refusal of an older repository names the upgrade command."""
    with pytest.raises(RuntimeError, match="nap-tool upgrade"):
        with connect(legacy / "nap_tool.sqlite"):
            pass


def test_cli(legacy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI reports each step, then that the repository is current."""
    monkeypatch.setenv("NAP_DATA_DIR", str(legacy))
    result = CliRunner().invoke(app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert f"DB_VERSION {DB_VERSION - 1} -> {DB_VERSION}" in result.output
    result = CliRunner().invoke(app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert "already current" in result.output


def test_compact_sheet_column_is_added_to_a_version_21_database(tmp_path: Path) -> None:
    """A database made before the column existed gets it, and a rerun changes nothing."""
    path = _make_db(tmp_path, 21)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP INDEX document_compact_sheet")
        connection.execute("ALTER TABLE document DROP COLUMN is_compact_sheet")
        connection.commit()
    assert upgrade_repository(tmp_path) == [
        (21, {"document_columns_added": 1}),
        (22, {"document_columns_added": 0}),
        (23, {"markdown_artifacts": 0}),
    ]
    with closing(sqlite3.connect(path)) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(document)")]
        connection.execute(
            "INSERT INTO dso (name, slug, created_at, updated_at) VALUES ('a','a','','')"
        )
        for number in (1, 2):
            connection.execute(
                "INSERT INTO document (dso_id, title, source, nap_year, is_compact_sheet, "
                "created_at, updated_at) VALUES (1, 't', 's', 2026, ?, '', '')",
                (1 if number == 1 else 0,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE document SET is_compact_sheet=1 WHERE id=2")
    assert "is_compact_sheet" in columns


def test_publication_status_upgrade_preserves_existing_documents(tmp_path: Path) -> None:
    """An older repository gains the nullable label without guessing any existing status."""
    path = _make_db(tmp_path, 22)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("ALTER TABLE document DROP COLUMN source_publication_status")
        connection.execute(
            "INSERT INTO dso (name, slug, created_at, updated_at) VALUES ('a','a','','')"
        )
        connection.execute(
            "INSERT INTO document (dso_id, title, source, version, created_at, updated_at) "
            "VALUES (1, 'FINAL.pdf', 'vnbdigital', '2026-11-01', '', '')"
        )
    assert upgrade_repository(tmp_path) == [
        (22, {"document_columns_added": 1}),
        (23, {"markdown_artifacts": 0}),
    ]
    assert upgrade_repository(tmp_path) == []
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT title, version, source_publication_status FROM document"
        ).fetchone() == ("FINAL.pdf", "2026-11-01", None)
