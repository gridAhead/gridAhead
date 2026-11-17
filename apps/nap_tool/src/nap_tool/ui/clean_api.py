# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Cleaning versions, column rules, and human review endpoints."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nap_tool.cleaning import (
    CleanConfig,
    clean_grid,
    csv_bytes,
    default_config,
    kept_row_indexes,
    load_cleaning_globals,
    with_tool_number_format,
)
from nap_tool.data import checked_file, write_bytes
from nap_tool.database.schema import connect


class NewVersion(BaseModel):
    """Create a named cleaning version from an extraction."""

    extract_id: int = Field(gt=0)
    title: str = Field(default="", max_length=120)
    header_row: int | None = Field(default=None, ge=1)


class VersionMetadata(BaseModel):
    """Update a cleaning version name, note, or selection."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=5000)
    is_selected: bool | None = None


class RuleUpdate(BaseModel):
    """Apply a complete validated rule set to one version."""

    config: CleanConfig
    expected_clean_hash: str
    expected_source_hash: str


class ReviewedGrid(BaseModel):
    """Save or confirm a manually reviewed grid."""

    rows: list[list[str]] = Field(min_length=1)
    expected_clean_hash: str
    expected_reviewed_hash: str | None = None
    confirm: bool = False


def _time() -> str:
    return datetime.now(UTC).isoformat()


def _grid(root: Path, relative: str, digest: str) -> list[list[str]]:
    try:
        path = checked_file(root, relative, digest)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.reader(source))


def _record(connection: sqlite3.Connection, clean_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT c.*, e.extract_table_hash, e.extract_table_path, "
        "e.extract_reviewed_table_hash, e.extract_reviewed_table_path, "
        "e.table_number, e.tool FROM clean_table c "
        "JOIN extract_table e ON e.id=c.extract_table_id WHERE c.id=?",
        (clean_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Cleaned version not found")
    return row


def _source(row: sqlite3.Row) -> tuple[str, str]:
    if row["extract_reviewed_table_path"] is not None:
        return row["extract_reviewed_table_path"], row["extract_reviewed_table_hash"]
    return row["extract_table_path"], row["extract_table_hash"]


def _artifacts(
    root: Path, extract_id: int, rows: list[list[str]], config: CleanConfig
) -> tuple[str, str, str, str, list[dict[str, str | int]]]:
    globals_config = load_cleaning_globals(
        Path(__file__).resolve().parents[3] / "config/cleaning.yaml"
    )
    cleaned, cells = clean_grid(rows, config, globals_config)
    content = csv_bytes(cleaned)
    digest = hashlib.sha256(content).hexdigest()
    relative = f"cleaned/{extract_id}/{digest}.csv"
    write_bytes(root, relative, content)
    cells_content = json.dumps(cells, ensure_ascii=False, sort_keys=True).encode("utf-8")
    cells_hash = hashlib.sha256(cells_content).hexdigest()
    cells_path = f"cleaned/{extract_id}/{cells_hash}.cells.json"
    write_bytes(root, cells_path, cells_content)
    return relative, digest, cells_path, cells_hash, cells


def _script_artifact(root: Path) -> tuple[str, str, str, str]:
    """Snapshot the engine and shared YAML used for this result."""
    content = (Path(__file__).resolve().parents[1] / "cleaning.py").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    relative = f"scripts/clean/{digest}.py"
    write_bytes(root, relative, content)
    globals_content = (Path(__file__).resolve().parents[3] / "config/cleaning.yaml").read_bytes()
    globals_hash = hashlib.sha256(globals_content).hexdigest()
    globals_path = f"scripts/clean/{globals_hash}.yaml"
    write_bytes(root, globals_path, globals_content)
    return relative, digest, globals_path, globals_hash


def install_clean_routes(router: APIRouter, root: Path) -> None:
    """Add cleaning endpoints to the FastAPI application.

    Args:
        router: API router to populate.
        root: External data repository.
    """

    @router.post("/api/clean-versions", status_code=201)
    def create_version(request: NewVersion) -> dict[str, object]:
        """Copy the effective extraction CSV and create an automatic result."""
        with connect(root / "nap_tool.sqlite") as connection:
            extract = connection.execute(
                "SELECT * FROM extract_table WHERE id=?", (request.extract_id,)
            ).fetchone()
            if extract is None:
                raise HTTPException(status_code=404, detail="Extracted table not found")
            source_path, source_hash = _source(extract)
            rows = _grid(root, source_path, source_hash)
            if not rows:
                raise HTTPException(status_code=422, detail="Extracted table is empty")
            previous = connection.execute(
                "SELECT clean_config FROM clean_table WHERE extract_table_id=? "
                "ORDER BY is_selected DESC, id DESC LIMIT 1",
                (request.extract_id,),
            ).fetchone()
            previous_config = (
                CleanConfig.model_validate_json(previous["clean_config"])
                if previous is not None and previous["clean_config"] != "{}"
                else None
            )
            if previous_config is not None and request.header_row in (
                None,
                previous_config.header_row,
            ):
                config = with_tool_number_format(previous_config, extract["tool"])
            else:
                header_row = request.header_row or 1
                if header_row > len(rows):
                    raise HTTPException(status_code=422, detail="Header row is outside the table")
                config = default_config(rows[header_row - 1], header_row, extract["tool"])
            if config.header_row > len(rows) or not any(
                cell.strip() for cell in rows[config.header_row - 1]
            ):
                raise HTTPException(
                    status_code=422, detail="Header row is invalid; check the extracted table first"
                )
            relative, digest, cells_path, cells_hash, _ = _artifacts(
                root, request.extract_id, rows, config
            )
            script_path, script_hash, globals_path, globals_hash = _script_artifact(root)
            notes = json.dumps(
                {"cleaning_globals_path": globals_path, "cleaning_globals_hash": globals_hash},
                ensure_ascii=False,
            )
            count = connection.execute(
                "SELECT COUNT(*) FROM clean_table WHERE extract_table_id=?", (request.extract_id,)
            ).fetchone()[0]
            title = request.title.strip() or f"Cleaning version {count + 1}"
            connection.execute(
                "UPDATE clean_table SET is_selected=0 WHERE extract_table_id=?",
                (request.extract_id,),
            )
            stamp = _time()
            clean_id = connection.execute(
                "INSERT INTO clean_table(extract_table_id, title, clean_table_hash, "
                "clean_table_path, clean_table_notes, clean_config, "
                "clean_cells_hash, clean_cells_path, "
                "clean_script, clean_script_hash, clean_source_hash, "
                "clean_created_at, clean_updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (
                    request.extract_id,
                    title,
                    digest,
                    relative,
                    notes,
                    config.model_dump_json(),
                    cells_hash,
                    cells_path,
                    script_path,
                    script_hash,
                    source_hash,
                    stamp,
                    stamp,
                ),
            ).fetchone()[0]
        return {"id": clean_id, "title": title}

    @router.delete("/api/clean-versions/{clean_id}")
    def delete_version(clean_id: int) -> dict[str, int | None]:
        """Delete a version and select the newest remaining version if needed."""
        with connect(root / "nap_tool.sqlite") as connection:
            row = _record(connection, clean_id)
            fixed_reference = connection.execute(
                "SELECT 1 FROM harmonize_field_source WHERE mode='fixed' AND clean_id=? LIMIT 1",
                (clean_id,),
            ).fetchone()
            if fixed_reference is not None:
                raise HTTPException(
                    status_code=409,
                    detail="This cleaned version is fixed in a harmonization scheme; "
                    "remove the link first",
                )
            connection.execute("DELETE FROM clean_table WHERE id=?", (clean_id,))
            if row["is_selected"]:
                replacement = connection.execute(
                    "SELECT id FROM clean_table WHERE extract_table_id=? ORDER BY id DESC LIMIT 1",
                    (row["extract_table_id"],),
                ).fetchone()
                if replacement is not None:
                    connection.execute(
                        "UPDATE clean_table SET is_selected=1 WHERE id=?", (replacement["id"],)
                    )
            selected = connection.execute(
                "SELECT id FROM clean_table WHERE extract_table_id=? AND is_selected=1 "
                "ORDER BY id DESC LIMIT 1",
                (row["extract_table_id"],),
            ).fetchone()
        return {"selected_id": selected["id"] if selected is not None else None}

    @router.get("/api/clean-review/{clean_id}")
    def get_review(clean_id: int) -> dict[str, object]:
        """Read source, automatic, and reviewed CSVs with status metadata."""
        with connect(root / "nap_tool.sqlite") as connection:
            row = _record(connection, clean_id)
        source_path, source_hash = _source(row)
        source_rows = _grid(root, source_path, source_hash)
        automatic_rows = _grid(root, row["clean_table_path"], row["clean_table_hash"])
        reviewed_rows = (
            _grid(root, row["clear_reviewed_table_path"], row["clear_reviewed_table_hash"])
            if row["clear_reviewed_table_path"]
            else None
        )
        cells: list[dict[str, str | int]] = []
        if row["clean_cells_path"]:
            try:
                cells_path = checked_file(root, row["clean_cells_path"], row["clean_cells_hash"])
            except (RuntimeError, ValueError) as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            with cells_path.open(encoding="utf-8") as source:
                cells = json.load(source)
        return {
            "id": clean_id,
            "extract_id": row["extract_table_id"],
            "title": row["title"] or f"Cleaning result #{clean_id}",
            "tool": row["tool"],
            "table_number": row["table_number"],
            "source_rows": source_rows,
            "automatic_rows": automatic_rows,
            "reviewed_rows": reviewed_rows,
            "rows": reviewed_rows or automatic_rows,
            "kept_rows": kept_row_indexes(
                len(source_rows), CleanConfig.model_validate_json(row["clean_config"])
            ),
            "cells": cells,
            "config": json.loads(row["clean_config"]),
            "source_hash": source_hash,
            "clean_source_hash": row["clean_source_hash"],
            "clean_hash": row["clean_table_hash"],
            "reviewed_hash": row["clear_reviewed_table_hash"],
            "is_stale": row["clean_source_hash"] != source_hash,
            "review_is_stale": bool(row["clear_reviewed_table_hash"])
            and row["clear_reviewed_source_hash"] != row["clean_table_hash"],
            "is_confirmed": bool(row["clean_is_confirmed"]),
            "is_selected": bool(row["is_selected"]),
            "note": row["clear_reviewed_table_notice"] or "",
        }

    @router.put("/api/clean-review/{clean_id}/rules")
    def update_rules(clean_id: int, request: RuleUpdate) -> dict[str, object]:
        """Recompute the automatic CSV from the effective extraction CSV."""
        with connect(root / "nap_tool.sqlite") as connection:
            row = _record(connection, clean_id)
            source_path, source_hash = _source(row)
            if (
                row["clean_table_hash"] != request.expected_clean_hash
                or source_hash != request.expected_source_hash
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Cleaning result or extraction source changed; reload the page",
                )
            rows = _grid(root, source_path, source_hash)
            if not rows:
                raise HTTPException(status_code=422, detail="Extracted table is empty")
            if request.config.header_row > len(rows):
                raise HTTPException(status_code=422, detail="Header row is outside the table")
            if not any(cell.strip() for cell in rows[request.config.header_row - 1]):
                raise HTTPException(status_code=422, detail="Selected header row is empty")
            width = max(map(len, rows))
            if any(index >= len(rows) for index in request.config.deleted_rows):
                raise HTTPException(status_code=422, detail="Deleted rows are outside the table")
            if any(column.index >= width for column in request.config.columns):
                raise HTTPException(status_code=422, detail="Column settings are outside the table")
            previous_config = CleanConfig.model_validate_json(row["clean_config"])
            config = request.config.model_copy(deep=True)
            if config.header_row != previous_config.header_row:
                headers = rows[config.header_row - 1]
                suggested = default_config(
                    headers + [""] * (width - len(headers)), config.header_row
                )
                configured = {rule.index: rule for rule in config.columns if rule.configured}
                config.columns = [configured.get(rule.index, rule) for rule in suggested.columns]
            script_path, script_hash, globals_path, globals_hash = _script_artifact(root)
            notes = json.loads(row["clean_table_notes"])
            notes["cleaning_globals_path"] = globals_path
            notes["cleaning_globals_hash"] = globals_hash
            if (
                row["clean_source_hash"] == source_hash
                and previous_config == config
                and row["clean_script_hash"] == script_hash
                and json.loads(row["clean_table_notes"]).get("cleaning_globals_hash")
                == globals_hash
            ):
                return {"clean_hash": row["clean_table_hash"], "unchanged": True}
            previous_auto = _grid(root, row["clean_table_path"], row["clean_table_hash"])
            previous_review = (
                _grid(root, row["clear_reviewed_table_path"], row["clear_reviewed_table_hash"])
                if row["clear_reviewed_table_path"]
                else None
            )
            relative, digest, cells_path, cells_hash, cells = _artifacts(
                root, row["extract_table_id"], rows, config
            )
            review_path = row["clear_reviewed_table_path"]
            review_hash = row["clear_reviewed_table_hash"]
            previous_kept = kept_row_indexes(len(rows), previous_config)
            if (
                previous_review is not None
                and row["clean_source_hash"] == source_hash
                and len(previous_review) == len(previous_auto) == len(previous_kept)
                and all(
                    len(reviewed) == len(automatic)
                    for reviewed, automatic in zip(previous_review, previous_auto)
                )
            ):
                new_auto = _grid(root, relative, digest)
                previous_by_source = {
                    source_index: (review_row, old_row)
                    for source_index, review_row, old_row in zip(
                        previous_kept, previous_review, previous_auto
                    )
                }
                new_kept = kept_row_indexes(len(rows), config)
                if all(
                    source_index not in previous_by_source
                    or len(previous_by_source[source_index][0]) == len(new_row)
                    for source_index, new_row in zip(new_kept, new_auto)
                ):
                    merged = [
                        [
                            reviewed if reviewed != old else new
                            for reviewed, old, new in zip(
                                *previous_by_source[source_index], new_row
                            )
                        ]
                        if source_index in previous_by_source
                        else new_row
                        for source_index, new_row in zip(new_kept, new_auto)
                    ]
                    content = csv_bytes(merged)
                    review_hash = hashlib.sha256(content).hexdigest()
                    review_path = f"clean_reviewed/{clean_id}/{review_hash}.csv"
                    write_bytes(root, review_path, content)
            if (
                review_path == row["clear_reviewed_table_path"]
                and previous_review is not None
                and len(previous_review) != len(kept_row_indexes(len(rows), config))
            ):
                review_path = review_hash = None
            connection.execute(
                "UPDATE clean_table SET clean_table_path=?, clean_table_hash=?, "
                "clean_config=?, clean_cells_path=?, clean_cells_hash=?, clean_source_hash=?, "
                "clean_script=?, clean_script_hash=?, clean_table_notes=?, "
                "clear_reviewed_table_path=?, clear_reviewed_table_hash=?, "
                "clear_reviewed_source_hash=NULL, clean_is_confirmed=0, "
                "clean_updated_at=? WHERE id=?",
                (
                    relative,
                    digest,
                    config.model_dump_json(),
                    cells_path,
                    cells_hash,
                    source_hash,
                    script_path,
                    script_hash,
                    json.dumps(notes, ensure_ascii=False),
                    review_path,
                    review_hash,
                    _time(),
                    clean_id,
                ),
            )
        return {"clean_hash": digest, "cells": cells}

    @router.put("/api/clean-review/{clean_id}")
    def save_review(clean_id: int, request: ReviewedGrid) -> dict[str, object]:
        """Save an immutable human CSV and optionally mark review complete."""
        if sum(len(row) for row in request.rows) > 300_000:
            raise HTTPException(status_code=413, detail="Table is too large to save on this page")
        with connect(root / "nap_tool.sqlite") as connection:
            row = _record(connection, clean_id)
            if (
                row["clean_table_hash"] != request.expected_clean_hash
                or row["clear_reviewed_table_hash"] != request.expected_reviewed_hash
            ):
                raise HTTPException(
                    status_code=409, detail="Cleaned table or review changed; reload the page"
                )
            automatic = _grid(root, row["clean_table_path"], row["clean_table_hash"])
            _, current_source_hash = _source(row)
            if request.confirm and row["clean_source_hash"] != current_source_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Extraction source changed; recalculate cleaning rules first",
                )
            if len(request.rows) != len(automatic) or any(
                len(edited) != len(source) for edited, source in zip(request.rows, automatic)
            ):
                raise HTTPException(status_code=422, detail="Review table dimensions cannot change")
            content = csv_bytes(request.rows)
            digest = hashlib.sha256(content).hexdigest()
            relative = f"clean_reviewed/{clean_id}/{digest}.csv"
            write_bytes(root, relative, content)
            connection.execute(
                "UPDATE clean_table SET clear_reviewed_table_path=?, "
                "clear_reviewed_table_hash=?, clear_reviewed_source_hash=?, "
                "clean_is_confirmed=?, clean_updated_at=? WHERE id=?",
                (
                    relative,
                    digest,
                    row["clean_table_hash"],
                    int(request.confirm),
                    _time(),
                    clean_id,
                ),
            )
        return {"reviewed_hash": digest, "is_confirmed": request.confirm}

    @router.patch("/api/clean-review/{clean_id}/metadata")
    def update_metadata(clean_id: int, request: VersionMetadata) -> dict[str, object]:
        """Rename, annotate, or select one cleaning version."""
        values = (request.title, request.note, request.is_selected)
        if sum(value is not None for value in values) != 1:
            raise HTTPException(status_code=422, detail="Change one item at a time")
        with connect(root / "nap_tool.sqlite") as connection:
            row = _record(connection, clean_id)
            if request.is_selected is True:
                connection.execute(
                    "UPDATE clean_table SET is_selected=0 WHERE extract_table_id=?",
                    (row["extract_table_id"],),
                )
            if request.title is not None:
                connection.execute(
                    "UPDATE clean_table SET title=?, clean_updated_at=? WHERE id=?",
                    (request.title.strip(), _time(), clean_id),
                )
            elif request.note is not None:
                connection.execute(
                    "UPDATE clean_table SET clear_reviewed_table_notice=?, "
                    "clean_updated_at=? WHERE id=?",
                    (request.note, _time(), clean_id),
                )
            else:
                connection.execute(
                    "UPDATE clean_table SET is_selected=?, clean_updated_at=? WHERE id=?",
                    (int(request.is_selected), _time(), clean_id),
                )
        return {"ok": True}
