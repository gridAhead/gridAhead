# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Upgrade a nap_data repository to this nap_tool's DB_VERSION, as an explicit step."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

import typer

from nap_tool.classifier.service import VERSIONS_DIR, is_generation, publish_pointer
from nap_tool.data import data_dir
from nap_tool.database.schema import DB_VERSION, require_version


def upgrade() -> None:
    """Upgrade nap_data in NAP_DATA_DIR to this nap_tool's DB_VERSION."""
    try:
        steps = upgrade_repository(data_dir())
    except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
        typer.echo(f"Upgrade failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not steps:
        typer.echo(f"DB_VERSION {DB_VERSION}: nap_data is already current")
        return
    for version, counts in steps:
        typer.echo(f"DB_VERSION {version} -> {version + 1}: {json.dumps(counts, sort_keys=True)}")
    typer.echo("Commit and push nap_data so others pick up the new version.")


def upgrade_repository(root: Path) -> list[tuple[int, dict[str, int]]]:
    """Apply every upgrade step from the repository's version to DB_VERSION.

    Each step changes the files first and is safe to rerun; the database records
    the new version only after its step finished.

    Args:
        root: Data repository root.

    Returns:
        The version each applied step started from, with its counts.

    Raises:
        RuntimeError: If the database is missing, newer than this nap_tool, or
            older than the first version an upgrade exists for.
    """
    path = root / "nap_tool.sqlite"
    if not path.is_file():
        raise RuntimeError(f"{path} not found; run `nap-tool discover` to create it")
    applied: list[tuple[int, dict[str, int]]] = []
    with closing(sqlite3.connect(path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 or version > DB_VERSION:
            require_version(connection, path)
        while version < DB_VERSION:
            step = UPGRADES.get(version)
            if step is None:
                raise RuntimeError(
                    f"{path} has DB_VERSION {version}; `nap-tool upgrade` starts at "
                    f"DB_VERSION {min(UPGRADES)}"
                )
            counts = step(root)
            with connection:
                connection.execute(f"PRAGMA user_version = {version + 1}")
            applied.append((version, counts))
            version += 1
    return applied


def _classification_pointers(root: Path) -> dict[str, int]:
    """DB_VERSION 20 -> 21: replace `scheme_<id>` symlinks with pointer files (ADR-0006)."""
    converted = 0
    for entry in sorted((root / "classified").glob("set_*/scheme_*")):
        scheme_id = entry.name.removeprefix("scheme_")
        if not scheme_id.isdigit():
            continue
        if entry.is_symlink():
            target = os.readlink(entry)
        elif entry.is_file():
            # A git checkout with core.symlinks=false stores a symlink as a text file
            # holding its target.
            target = entry.read_text(encoding="utf-8").strip()
        else:
            raise RuntimeError(f"{entry} is a directory, not a link; move it aside and rerun")
        generation = target.replace("\\", "/").removeprefix(f"{VERSIONS_DIR}/")
        if not is_generation(int(scheme_id), generation):
            raise RuntimeError(f"{entry} does not point into {VERSIONS_DIR}/: {target}")
        if not (entry.parent / VERSIONS_DIR / generation).is_dir():
            raise RuntimeError(f"{entry} points to a missing generation: {target}")
        publish_pointer(entry.parent, int(scheme_id), generation)
        entry.unlink()
        converted += 1
    return {"classification_pointers": converted}


def _compact_sheet_column(root: Path) -> dict[str, int]:
    """DB_VERSION 21 -> 22: add `document.is_compact_sheet` and its unique index."""
    with closing(sqlite3.connect(root / "nap_tool.sqlite")) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(document)")}
        added = "is_compact_sheet" not in columns
        with connection:
            if added:
                connection.execute(
                    "ALTER TABLE document ADD COLUMN is_compact_sheet INTEGER NOT NULL "
                    "DEFAULT 0 CHECK (is_compact_sheet IN (0, 1))"
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS document_compact_sheet "
                "ON document(dso_id, nap_year) WHERE is_compact_sheet = 1"
            )
    return {"document_columns_added": int(added)}


UPGRADES: dict[int, Callable[[Path], dict[str, int]]] = {
    20: _classification_pointers,
    21: _compact_sheet_column,
}
