# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Set management and live membership counts for the Settings page."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nap_tool.classifier.service import is_grid_measure_type
from nap_tool.database.schema import connect
from nap_tool.harmonize import field_key

PositiveId = Annotated[int, Field(gt=0)]
NapYear = Annotated[int, Field(ge=2000, le=2100)]


class SetFilters(BaseModel):
    table_type_id: PositiveId
    dso_ids: list[PositiveId] = Field(default_factory=list)
    years: list[NapYear] = Field(default_factory=list)


class CurrentSchemeUpdate(BaseModel):
    current_scheme_id: PositiveId | None
    expected_current_scheme_id: PositiveId | None


class NewSet(SetFilters):
    name: str = Field(min_length=1, max_length=200)


def _validate(connection: sqlite3.Connection, filters: SetFilters) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM table_type WHERE id=?", (filters.table_type_id,)
        ).fetchone()
        is None
    ):
        raise HTTPException(status_code=422, detail="Unknown table type")
    known = {row[0] for row in connection.execute("SELECT id FROM dso")}
    if not set(filters.dso_ids) <= known:
        raise HTTPException(status_code=422, detail="Unknown VNB")


def matching_members(
    connection: sqlite3.Connection, filters: SetFilters
) -> tuple[list[tuple[sqlite3.Row, int | None]], set[int]]:
    rows = connection.execute(
        "SELECT d.*, e.id AS extract_id FROM extract_table e "
        "JOIN extract_table_type t ON t.extract_table_id=e.id "
        "JOIN document d ON d.id=e.document_id "
        "WHERE t.table_type_id=? AND d.is_selected=1 "
        "AND e.is_selected=1 AND e.extract_is_archived=0 "
        "AND EXISTS (SELECT 1 FROM clean_table c "
        "WHERE c.extract_table_id=e.id AND c.is_selected=1)",
        (filters.table_type_id,),
    ).fetchall()
    matching = []
    undated: set[int] = set()
    dso_ids, years = set(filters.dso_ids), set(filters.years)
    for row in rows:
        if dso_ids and row["dso_id"] not in dso_ids:
            continue
        year = row["nap_year"]
        if year is None:
            undated.add(row["id"])
        if years and year not in years:
            continue
        matching.append((row, year))
    return matching, undated


def _counts(connection: sqlite3.Connection, filters: SetFilters) -> dict[str, int]:
    rows, undated = matching_members(connection, filters)
    return {
        "table_count": len(rows),
        "vnb_count": len({row["dso_id"] for row, _ in rows}),
        "undated_document_count": len(undated),
    }


def _summary(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    filters = SetFilters(
        table_type_id=row["table_type_id"],
        dso_ids=json.loads(row["dso_ids"]),
        years=json.loads(row["years"]),
    )
    return {
        **dict(row),
        **filters.model_dump(),
        **_counts(connection, filters),
        "is_grid_measure": is_grid_measure_type(connection, row["table_type_id"]),
    }


def router(root: Path) -> APIRouter:
    api = APIRouter(prefix="/api/harmonize/sets", tags=["sets"])

    @api.get("")
    def list_sets() -> list[dict[str, object]]:
        with connect(root / "nap_tool.sqlite") as connection:
            return [
                _summary(connection, row)
                for row in connection.execute("SELECT * FROM harmonize_set ORDER BY id")
            ]

    @api.get("/options")
    def options() -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            years = {
                year
                for row in connection.execute("SELECT * FROM document")
                if (year := row["nap_year"]) is not None
            }
            vnbs = [
                dict(row) for row in connection.execute("SELECT id,name FROM dso ORDER BY name,id")
            ]
        return {"years": sorted(years, reverse=True), "vnbs": vnbs}

    @api.post("/preview")
    def preview(filters: SetFilters) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            _validate(connection, filters)
            counts = _counts(connection, filters)
        return {**counts, "zero_match": counts["table_count"] == 0}

    @api.post("", status_code=201)
    def create_set(request: NewSet) -> dict[str, object]:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name is required")
        with connect(root / "nap_tool.sqlite") as connection:
            _validate(connection, request)
            try:
                cursor = connection.execute(
                    "INSERT INTO harmonize_set(name,slug,table_type_id,dso_ids,years,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        name,
                        field_key(name),
                        request.table_type_id,
                        json.dumps(sorted(set(request.dso_ids))),
                        json.dumps(sorted(set(request.years))),
                        datetime.now(UTC).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise HTTPException(status_code=409, detail="Set name already exists") from error
            row = connection.execute(
                "SELECT * FROM harmonize_set WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            result = _summary(connection, row)
        return {**result, "zero_match": result["table_count"] == 0}

    @api.put("/{set_id}")
    def update_set(set_id: int, request: NewSet) -> dict[str, object]:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name is required")
        with connect(root / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            selected = connection.execute(
                "SELECT * FROM harmonize_set WHERE id=?", (set_id,)
            ).fetchone()
            if selected is None:
                raise HTTPException(status_code=404, detail="Set not found")
            _validate(connection, request)
            dso_ids, years = sorted(set(request.dso_ids)), sorted(set(request.years))
            changed = (
                selected["table_type_id"] != request.table_type_id
                or sorted(json.loads(selected["dso_ids"])) != dso_ids
                or sorted(json.loads(selected["years"])) != years
            )
            try:
                connection.execute(
                    "UPDATE harmonize_set SET name=?,slug=?,table_type_id=?,dso_ids=?,years=? "
                    "WHERE id=?",
                    (
                        name,
                        field_key(name),
                        request.table_type_id,
                        json.dumps(dso_ids),
                        json.dumps(years),
                        set_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise HTTPException(status_code=409, detail="Set name already exists") from error
            if changed:
                connection.execute(
                    "UPDATE harmonize_set_output SET source_manifest_hash=NULL WHERE set_id=?",
                    (set_id,),
                )
            row = connection.execute("SELECT * FROM harmonize_set WHERE id=?", (set_id,)).fetchone()
            result = _summary(connection, row)
        return {**result, "zero_match": result["table_count"] == 0}

    @api.put("/{set_id}/current-scheme")
    def current_scheme(set_id: int, request: CurrentSchemeUpdate) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            selected = connection.execute(
                "SELECT * FROM harmonize_set WHERE id=?", (set_id,)
            ).fetchone()
            if selected is None:
                raise HTTPException(status_code=404, detail="Set not found")
            if selected["current_scheme_id"] != request.expected_current_scheme_id:
                raise HTTPException(
                    status_code=409, detail="Set default changed; reload before saving"
                )
            if request.current_scheme_id is not None:
                scheme = connection.execute(
                    "SELECT id FROM harmonize_scheme WHERE id=?",
                    (request.current_scheme_id,),
                ).fetchone()
                if scheme is None:
                    raise HTTPException(status_code=422, detail="Choose an existing scheme")
            connection.execute(
                "UPDATE harmonize_set SET current_scheme_id=? WHERE id=?",
                (request.current_scheme_id, set_id),
            )
            return _summary(
                connection,
                connection.execute("SELECT * FROM harmonize_set WHERE id=?", (set_id,)).fetchone(),
            )

    @api.delete("/{set_id}")
    def delete_set(set_id: int) -> dict[str, bool]:
        with connect(root / "nap_tool.sqlite") as connection:
            paths = [
                row[0]
                for row in connection.execute(
                    "SELECT output_path FROM harmonize_set_output WHERE set_id=?", (set_id,)
                )
            ]
            cursor = connection.execute("DELETE FROM harmonize_set WHERE id=?", (set_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Set not found")
        from nap_tool.data import resolve_path

        for path in paths:
            if not re.fullmatch(r"harmonized/scheme_\d+/(?:output|[0-9a-f]{64})\.csv", path):
                resolve_path(root, path).unlink(missing_ok=True)
        return {"deleted": True}

    return api
