# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""DB_VERSION checks at every metadata database open."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nap_tool.classifier.service import database
from nap_tool.cli import app
from nap_tool.database.schema import DB_VERSION, SCHEMA, connect, require_version
from nap_tool.ui.server import create_app

# sha256 of SCHEMA per DB_VERSION. A schema change makes this test fail: if old
# code cannot read the new data or vice versa, bump DB_VERSION and add an entry;
# for a formatting-only change, replace the hash of the current version.
SCHEMA_FINGERPRINTS = {
    20: "39590f199ca6e17b4338a948efeb92aef145d3295e76df7bf53141ca95f30573",
    # 21: classification output pointer files replace symlinks (ADR-0006).
    21: "02968b3fc4d561ca64ceeb34721baccfd12c6b9d63b649c69aee9c8fc4f6d617",
    # 22: document.is_compact_sheet and its partial unique index.
    22: "a9037f25d2fe7732b0839c567a70a79442299aa0f0e32fe66087e0a4e87d8ad6",
    # 23: document.source_publication_status.
    23: "7f983bf0fac659067b352956ef954bd3f31a706c11965846ba9ea923782a7cf7",
    24: "9df846c4eaa9f67dbb5fc1e28a83070a7d8dfd3a258c7da3c133eb69f0305f9a",
}

NEWER = (DB_VERSION + 1, "update nap_tool")
OLDER = (DB_VERSION - 1, "update nap_data")


def _set_version(path: Path, version: int) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA user_version = {version}")


def _user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Create a data repository with an empty current-version database.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Repository root.
    """
    with connect(tmp_path / "nap_tool.sqlite"):
        pass
    return tmp_path


def test_schema_change_needs_a_version_decision() -> None:
    """Changing SCHEMA fails until DB_VERSION and the fingerprint are updated."""
    digest = hashlib.sha256(SCHEMA.encode()).hexdigest()
    assert SCHEMA_FINGERPRINTS.get(DB_VERSION) == digest, (
        "SCHEMA or DB_VERSION changed: bump DB_VERSION if old code cannot read the new "
        "data or vice versa, then update SCHEMA_FINGERPRINTS"
    )


def test_new_database_gets_current_version(repository: Path) -> None:
    """connect() stamps a fresh database with DB_VERSION."""
    assert _user_version(repository / "nap_tool.sqlite") == DB_VERSION


@pytest.mark.parametrize("version,hint", [NEWER, OLDER])
def test_connect_refuses_other_version(repository: Path, version: int, hint: str) -> None:
    """A version mismatch names the repository to update and changes nothing."""
    path = repository / "nap_tool.sqlite"
    _set_version(path, version)
    with pytest.raises(RuntimeError, match=hint):
        with connect(path):
            pass
    assert _user_version(path) == version


def test_connect_refuses_unversioned_legacy_database(tmp_path: Path) -> None:
    """An old database without user_version points to the legacy import."""
    path = tmp_path / "nap_tool.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE document (document_id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="nap-tool migrate --from-db"):
        with connect(path):
            pass


def test_require_version_reports_empty_database(tmp_path: Path) -> None:
    """A read-only open of an empty file asks for discover instead of creating tables."""
    path = tmp_path / "nap_tool.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(RuntimeError, match="nap-tool discover"):
            require_version(connection, path)


@pytest.mark.parametrize("version,hint", [NEWER, OLDER])
def test_ui_refuses_to_start(repository: Path, version: int, hint: str) -> None:
    """create_app() stops before serving a mismatched repository."""
    _set_version(repository / "nap_tool.sqlite", version)
    with pytest.raises(RuntimeError, match=hint):
        create_app(repository)


def test_ui_startup_does_not_write(tmp_path: Path) -> None:
    """Starting the UI on an empty database file leaves the file untouched."""
    path = tmp_path / "nap_tool.sqlite"
    path.touch()
    with pytest.raises(RuntimeError, match="has no schema"):
        create_app(tmp_path)
    assert path.stat().st_size == 0


def test_ui_requests_check_version_after_startup(repository: Path) -> None:
    """A nap_data pull under a running UI fails reads and writes with the update hint."""
    client = TestClient(create_app(repository), raise_server_exceptions=False)
    _set_version(repository / "nap_tool.sqlite", DB_VERSION + 1)
    responses = (
        client.get("/api/table-types"),
        client.get("/api/harmonize/schemes"),
        client.put("/api/extract-review/1", json={"rows": [["a"]], "source_hash": "x"}),
        client.patch("/api/extract-review/1/metadata", json={"source_hash": "x", "note": "n"}),
    )
    for response in responses:
        assert response.status_code == 409
        assert "update nap_tool" in response.json()["detail"]


def test_classifier_checks_version(repository: Path) -> None:
    """The classifier's read-only connection is version-checked too."""
    _set_version(repository / "nap_tool.sqlite", DB_VERSION - 1)
    with pytest.raises(RuntimeError, match="update nap_data"):
        with database(repository):
            pass


def test_classifier_missing_database_names_path(tmp_path: Path) -> None:
    """A missing database points to NAP_DATA_DIR, not to the legacy import."""
    with pytest.raises(ValueError, match="check NAP_DATA_DIR"):
        with database(tmp_path):
            pass


def test_sync_identifiers_reports_version_error(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sync-dso-identifiers prints the mismatch instead of a traceback."""
    _set_version(repository / "nap_tool.sqlite", DB_VERSION + 1)
    monkeypatch.setenv("NAP_DATA_DIR", str(repository))
    result = CliRunner().invoke(app, ["sync-dso-identifiers"])
    assert result.exit_code == 1
    assert "update nap_tool" in result.output
    assert isinstance(result.exception, SystemExit)


def test_ui_command_reports_corrupt_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that is not SQLite stops `nap-tool ui` with a message, not a traceback."""
    (tmp_path / "nap_tool.sqlite").write_bytes(b"not a database" * 10)
    monkeypatch.setenv("NAP_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["ui"])
    assert result.exit_code == 1
    assert "UI cannot start" in result.output
    assert isinstance(result.exception, SystemExit)


def test_ui_command_prints_version(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`nap-tool ui` prints the matching DB_VERSION before serving."""
    monkeypatch.setenv("NAP_DATA_DIR", str(repository))
    with patch("nap_tool.ui.commands.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["ui"])
    assert result.exit_code == 0, result.output
    assert f"DB_VERSION {DB_VERSION}" in result.output
    run.assert_called_once()
