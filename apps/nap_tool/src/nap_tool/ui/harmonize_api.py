# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Harmonization schemes, source column bindings, and CSV generation."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from nap_tool.cleaning import CleanConfig
from nap_tool.data import checked_file, resolve_path
from nap_tool.database.schema import TABLE_TYPE_GRID_MEASURES, connect
from nap_tool.harmonize import csv_content, csv_rows, field_key, group_headers
from nap_tool.ui.sets_api import SetFilters, matching_members

OUTPUT_SCHEMA_VERSION = 5
PROVENANCE = [
    "dso_slug",
]


class SourceBinding(BaseModel):
    """One concrete column occurrence or its automatic stage resolution."""

    extract_id: int = Field(gt=0)
    column_index: int = Field(ge=0)
    header: str
    mode: Literal["auto", "fixed"] = "auto"
    stage: Literal["clean_review", "clean_table", "extract_reviewed", "extract_table"] | None = None
    clean_id: int | None = None
    source_hash: str | None = None

    @model_validator(mode="after")
    def validate_fixed(self) -> SourceBinding:
        """Require a stage when the association is fixed to a version."""
        if self.mode == "fixed" and self.stage is None:
            raise ValueError("Fixed source must specify a stage")
        return self


class FieldDraft(BaseModel):
    """Editable target field with concrete source bindings."""

    key: str = ""
    title: str = Field(min_length=1, max_length=240)
    scope: str = Field(default="", max_length=240)
    sources: list[SourceBinding] = Field(default_factory=list)


class TableRule(BaseModel):
    """Interpretation of physical CSV rows for one measure table."""

    header_row: int = Field(default=1, ge=1)
    excluded_rows: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_rows(self) -> TableRule:
        if len(self.excluded_rows) != len(set(self.excluded_rows)):
            raise ValueError("Excluded row numbers cannot repeat")
        if any(row <= self.header_row for row in self.excluded_rows):
            raise ValueError("Only data rows after the header can be excluded")
        return self


class NewScheme(BaseModel):
    """Create a blank scheme or copy an existing one."""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    creation_mode: Literal["copy", "blank", "lcs80", "lcs60"] | None = None
    initial_set_id: int | None = Field(default=None, gt=0)
    copy_from_id: int | None = Field(default=None, gt=0)


class SchemeUpdate(BaseModel):
    """Replace a scheme's editable field mapping."""

    name: str = Field(min_length=1, max_length=120)
    fields: list[FieldDraft]
    table_settings: dict[int, TableRule] | None = None
    expected_updated_at: str


class SchemeInitialSetUpdate(BaseModel):
    initial_set_id: int | None = Field(default=None, gt=0)
    expected_updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _scheme(connection: sqlite3.Connection, scheme_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM harmonize_scheme WHERE id=?", (scheme_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return row


def _source_index(variant: dict[str, object]) -> dict[int, int]:
    """Map zero-based source row indexes to row positions in this variant's CSV.

    Cleaning can delete rows, so a cleaned CSV holds fewer rows than its source. Row numbers
    in harmonization always count source rows, which stay stable when rows are deleted.
    """
    deleted = set(variant.get("deleted_rows", []))  # type: ignore[arg-type]
    rows = variant["rows"]
    source_count = len(rows) + len(deleted)  # type: ignore[arg-type]
    kept = (index for index in range(source_count) if index not in deleted)
    return {source: position for position, source in enumerate(kept)}


def _source_numbers(row_count: int, deleted_rows: list[int]) -> list[int]:
    """Return the one-based source row number of each row in a cleaned CSV."""
    deleted = set(deleted_rows)
    numbers = (index + 1 for index in range(row_count + len(deleted)) if index not in deleted)
    return list(numbers)


def _rows(root: Path, variant: dict[str, object]) -> list[list[str]]:
    try:
        path = checked_file(root, str(variant["path"]), str(variant["hash"]))
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return csv_rows(path.read_bytes())


def _table_settings(scheme: sqlite3.Row) -> dict[int, TableRule]:
    return {
        int(extract_id): TableRule.model_validate(value)
        for extract_id, value in json.loads(scheme["table_settings"]).items()
    }


def _selected_clean_header_settings(
    connection: sqlite3.Connection, table_type: int | None
) -> dict[int, TableRule]:
    """Snapshot selected cleaning header rows for a newly created scheme."""
    rows = connection.execute(
        "SELECT c.extract_table_id, c.clean_config FROM clean_table c "
        "JOIN extract_table e ON e.id=c.extract_table_id "
        "JOIN extract_table_type et ON et.extract_table_id=e.id "
        "WHERE c.is_selected=1 AND (? IS NULL OR et.table_type_id=?) "
        "AND e.is_selected=1 AND e.extract_is_archived=0",
        (table_type, table_type),
    ).fetchall()
    settings = {}
    for row in rows:
        header_row = CleanConfig.model_validate_json(row["clean_config"]).header_row
        if header_row > 1:
            settings[row["extract_table_id"]] = TableRule(header_row=header_row)
    return settings


def _variants(
    extract: sqlite3.Row, clean: sqlite3.Row | None, root: Path, rule: TableRule
) -> list[dict[str, object]]:
    candidates: list[tuple[str, int | None, str | None, str | None]] = []
    if clean is not None:
        candidates.extend(
            [
                (
                    "clean_review",
                    clean["id"],
                    clean["clear_reviewed_table_path"],
                    clean["clear_reviewed_table_hash"],
                ),
                ("clean_table", clean["id"], clean["clean_table_path"], clean["clean_table_hash"]),
            ]
        )
    candidates.extend(
        [
            (
                "extract_reviewed",
                None,
                extract["extract_reviewed_table_path"],
                extract["extract_reviewed_table_hash"],
            ),
            ("extract_table", None, extract["extract_table_path"], extract["extract_table_hash"]),
        ]
    )
    deleted_rows = (
        CleanConfig.model_validate_json(clean["clean_config"]).deleted_rows if clean else []
    )
    result: list[dict[str, object]] = []
    for stage, clean_id, path, digest in candidates:
        if not path or not digest:
            continue
        variant: dict[str, object] = {
            "stage": stage,
            "clean_id": clean_id,
            "path": path,
            "hash": digest,
            "deleted_rows": deleted_rows if clean_id is not None else [],
        }
        rows = _rows(root, variant)
        source_count = len(rows) + len(variant["deleted_rows"])  # type: ignore[arg-type]
        headers = rows[rule.header_row - 1] if len(rows) >= rule.header_row else []
        variant["headers"] = headers
        variant["header_row"] = rule.header_row
        variant["physical_row_count"] = source_count
        variant["samples"] = [
            list(
                dict.fromkeys(
                    row[index].strip()
                    for row_number, row in zip(
                        _source_numbers(len(rows), variant["deleted_rows"]), rows, strict=True
                    )
                    if row_number > rule.header_row
                    and row_number not in rule.excluded_rows
                    and len(row) > index
                    and row[index].strip()
                )
            )[:3]
            for index in range(len(headers))
        ]
        variant["row_count"] = sum(
            row_number > rule.header_row and row_number not in rule.excluded_rows
            for row_number in _source_numbers(len(rows), variant["deleted_rows"])
        )
        result.append(variant)
    return result


def _inventory(
    connection: sqlite3.Connection,
    root: Path,
    settings: dict[int, TableRule] | None = None,
    *,
    table_type: int | None = TABLE_TYPE_GRID_MEASURES,
    extract_ids: set[int] | None = None,
) -> list[dict[str, object]]:
    settings = settings or {}
    if extract_ids is not None and not extract_ids:
        return []
    member_clause = (
        " AND e.id IN (" + ",".join("?" for _ in extract_ids) + ")"
        if extract_ids is not None
        else ""
    )
    extracts = connection.execute(
        "SELECT e.*, et.table_type_id AS table_type, d.title AS document_title, d.dso_id, "
        "v.slug AS dso_slug, v.name AS vnb_name "
        "FROM extract_table e JOIN extract_table_type et ON et.extract_table_id=e.id "
        "JOIN document d ON d.id=e.document_id "
        "JOIN dso v ON v.id=d.dso_id "
        "WHERE (? IS NULL OR et.table_type_id=?) AND e.is_selected=1 AND e.extract_is_archived=0 "
        + member_clause
        + " ORDER BY v.name, d.id, e.id",
        (table_type, table_type, *(extract_ids or [])),
    ).fetchall()
    result = []
    for extract in extracts:
        rule = settings.get(extract["id"], TableRule())
        clean = connection.execute(
            "SELECT * FROM clean_table WHERE extract_table_id=? AND is_selected=1 "
            "ORDER BY id DESC LIMIT 1",
            (extract["id"],),
        ).fetchone()
        variants = _variants(extract, clean, root, rule)
        if not variants:
            continue
        result.append(
            {
                "extract_id": extract["id"],
                "table_type": extract["table_type"],
                "document_id": extract["document_id"],
                "document_title": extract["document_title"],
                "dso_slug": extract["dso_slug"],
                "vnb_name": extract["vnb_name"],
                "tool": extract["tool"],
                "table_number": extract["table_number"],
                "extract_is_confirmed": bool(extract["extract_is_confirmed"]),
                "clean_is_confirmed": bool(clean["clean_is_confirmed"]) if clean else False,
                "header_row": rule.header_row,
                "excluded_rows": rule.excluded_rows,
                "versions": variants,
            }
        )
    return result


def _lcs_fields(key: str, tables: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    sources: dict[str, list[dict[str, object]]] = {}
    for table in tables:
        version = table["versions"][0]
        for index, header in enumerate(version["headers"]):
            if not header.strip():
                continue
            counts[header] += 1
            sources.setdefault(header, []).append(
                {
                    "extract_id": table["extract_id"],
                    "column_index": index,
                    "header": header,
                    "mode": "auto",
                    "stage": None,
                    "clean_id": None,
                    "source_hash": None,
                }
            )
    names = sorted(counts, key=lambda name: (-counts[name], name.casefold()))
    groups = group_headers(names, 0.8 if key == "lcs80" else 0.6)
    used: set[str] = set()
    fields = []
    for group in groups:
        base = field_key(group[0])
        unique = base
        suffix = 2
        while unique in used:
            unique = f"{base}_{suffix}"
            suffix += 1
        used.add(unique)
        fields.append(
            {
                "key": unique,
                "title": group[0],
                "scope": "",
                "sources": [source for name in group for source in sources[name]],
            }
        )
    return fields


def _fields(
    connection: sqlite3.Connection, scheme: sqlite3.Row, tables: list[dict[str, object]]
) -> list[dict[str, object]]:
    records = connection.execute(
        "SELECT id,field_key,title,scope FROM harmonize_field "
        "WHERE scheme_id=? ORDER BY position,id",
        (scheme["id"],),
    ).fetchall()
    bindings: dict[int, list[dict[str, object]]] = {row["id"]: [] for row in records}
    for row in connection.execute(
        "SELECT s.field_id,s.extract_id,s.column_index,s.header,s.mode,s.stage,"
        "s.clean_id,s.source_hash FROM harmonize_field_source s "
        "JOIN harmonize_field f ON f.id=s.field_id WHERE f.scheme_id=? "
        "ORDER BY f.position,f.id,s.position",
        (scheme["id"],),
    ):
        bindings[row["field_id"]].append(
            {
                key: row[key]
                for key in (
                    "extract_id",
                    "column_index",
                    "header",
                    "mode",
                    "stage",
                    "clean_id",
                    "source_hash",
                )
            }
        )
    return [
        {
            "key": row["field_key"],
            "title": row["title"],
            "scope": row["scope"],
            "sources": bindings[row["id"]],
        }
        for row in records
    ]


def _insert_fields(
    connection: sqlite3.Connection, scheme_id: int, fields: list[dict[str, object]], stamp: str
) -> None:
    for position, field in enumerate(fields):
        field_id = connection.execute(
            "INSERT INTO harmonize_field(scheme_id,field_key,position,title,scope,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                scheme_id,
                field["key"],
                position,
                field["title"],
                field["scope"],
                stamp,
                stamp,
            ),
        ).lastrowid
        for source_position, source in enumerate(field["sources"]):
            connection.execute(
                "INSERT INTO harmonize_field_source("
                "field_id,position,extract_id,column_index,header,mode,stage,clean_id,"
                "source_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    field_id,
                    source_position,
                    source["extract_id"],
                    source["column_index"],
                    source["header"],
                    source["mode"],
                    source["stage"],
                    source["clean_id"],
                    source["source_hash"],
                ),
            )


def _summary(row: sqlite3.Row, connection: sqlite3.Connection) -> dict[str, object]:
    return {
        "initial_set_id": row["initial_set_id"],
        "slug": row["slug"],
        "id": row["id"],
        "name": row["name"],
        "copy_from_scheme_id": row["copy_from_scheme_id"],
        "has_output": False,
        "output_is_stale": False,
        "generated_at": None,
        "updated_at": row["updated_at"],
    }


def _validate_initial_set(connection: sqlite3.Connection, set_id: int | None) -> None:
    if set_id is None:
        return
    row = connection.execute(
        "SELECT table_type_id FROM harmonize_set WHERE id=?", (set_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=422, detail="Set must exist")


def _set_member_ids(connection: sqlite3.Connection, set_id: int) -> set[int]:
    selected = connection.execute("SELECT * FROM harmonize_set WHERE id=?", (set_id,)).fetchone()
    if selected is None:
        raise HTTPException(status_code=404, detail="Set not found")
    rows, _ = matching_members(
        connection,
        SetFilters(
            table_type_id=selected["table_type_id"],
            dso_ids=json.loads(selected["dso_ids"]),
            years=json.loads(selected["years"]),
        ),
    )
    return {row["extract_id"] for row, _ in rows}


def _pair_tables(
    connection: sqlite3.Connection,
    root: Path,
    scheme: sqlite3.Row,
    set_id: int,
) -> list[dict[str, object]]:
    selected = connection.execute("SELECT * FROM harmonize_set WHERE id=?", (set_id,)).fetchone()
    if selected is None:
        raise HTTPException(status_code=404, detail="Set not found")
    _validate_initial_set(connection, set_id)
    rows, _ = matching_members(
        connection,
        SetFilters(
            table_type_id=selected["table_type_id"],
            dso_ids=json.loads(selected["dso_ids"]),
            years=json.loads(selected["years"]),
        ),
    )
    members = {row["extract_id"]: (row, year) for row, year in rows}
    tables = _inventory(
        connection,
        root,
        _table_settings(scheme),
        table_type=selected["table_type_id"],
        extract_ids=set(members),
    )
    for table in tables:
        document, year = members[table["extract_id"]]
        table["nap_year"] = year
        table["document_key"] = (document["hash"] or "")[:16]
    return tables


def _pair_manifest(fields: list[dict[str, object]], tables: list[dict[str, object]]) -> str | None:
    base = _current_manifest_hash(fields, tables)
    if base is None:
        return None
    return hashlib.sha256(
        _json(
            {
                "base": base,
                "members": [
                    {
                        "id": table["extract_id"],
                        "year": table["nap_year"],
                        "document": table["document_key"],
                        "document_id": table["document_id"],
                        "vnb": table["dso_slug"],
                        "tool": table["tool"],
                        "number": table["table_number"],
                        "versions": [
                            {key: version[key] for key in ("stage", "clean_id", "hash")}
                            for version in table["versions"]
                        ],
                    }
                    for table in tables
                ],
            }
        ).encode()
    ).hexdigest()


def _pair_summary(
    connection: sqlite3.Connection,
    root: Path,
    scheme: sqlite3.Row,
    set_id: int,
) -> dict[str, object]:
    _validate_initial_set(connection, set_id)
    row = connection.execute(
        "SELECT * FROM harmonize_set_output WHERE set_id=? AND scheme_id=?", (set_id, scheme["id"])
    ).fetchone()
    stale = False
    if row:
        try:
            tables = _pair_tables(connection, root, scheme, set_id)
            current = _pair_manifest(_fields(connection, scheme, tables), tables)
            stale = current is None or current != row["source_manifest_hash"]
            checked_file(root, row["output_path"], row["output_hash"])
        except (HTTPException, RuntimeError, ValueError):
            stale = True
    return {
        "set_id": set_id,
        "has_output": row is not None,
        "output_is_stale": stale,
        "generated_at": row["generated_at"] if row else None,
    }


def _new_slug(connection: sqlite3.Connection, name: str) -> str:
    slug = field_key(name)
    if not name.strip():
        raise HTTPException(status_code=422, detail="Scheme name cannot be empty")
    if any(
        row["slug"] == slug or field_key(row["name"]) == slug
        for row in connection.execute("SELECT name,slug FROM harmonize_scheme")
    ):
        raise HTTPException(status_code=409, detail="A scheme with this name already exists")
    return slug


def _current_manifest_hash(
    fields: list[dict[str, object]], tables: list[dict[str, object]]
) -> str | None:
    """Fingerprint the currently resolved sources without loading output rows.

    Args:
        fields: Target fields and source bindings.
        tables: Available selected measure tables.

    Returns:
        Current fingerprint, or None if a binding can no longer be resolved.
    """
    manifest = []
    for table in tables:
        versions = table["versions"]
        refs = [
            ref
            for field in fields
            for ref in field["sources"]
            if ref["extract_id"] == table["extract_id"]
        ]
        resolved = []
        for ref in refs:
            version = (
                versions[0]
                if ref["mode"] == "auto"
                else next(
                    (
                        item
                        for item in versions
                        if item["stage"] == ref["stage"] and item["clean_id"] == ref["clean_id"]
                    ),
                    None,
                )
            )
            if (
                version is None
                or ref["column_index"] >= len(version["headers"])
                or (ref["mode"] == "fixed" and ref["source_hash"] != version["hash"])
            ):
                return None
            resolved.append(
                {
                    "column_index": ref["column_index"],
                    "stage": version["stage"],
                    "clean_id": version["clean_id"],
                    "hash": version["hash"],
                }
            )
        manifest.append(
            {
                "extract_id": table["extract_id"],
                "header_row": table.get("header_row", 1),
                "excluded_rows": table.get("excluded_rows", []),
                "extract_is_confirmed": table.get("extract_is_confirmed", False),
                "clean_is_confirmed": table.get("clean_is_confirmed", False),
                "sources": resolved,
                "fallback_hash": versions[0]["hash"] if not resolved else None,
            }
        )
    return hashlib.sha256(
        _json(
            {"output_schema_version": OUTPUT_SCHEMA_VERSION, "fields": fields, "sources": manifest}
        ).encode()
    ).hexdigest()


def _validated_fields(
    fields: list[FieldDraft], tables: list[dict[str, object]]
) -> list[dict[str, object]]:
    available = {table["extract_id"]: table for table in tables}
    keys: set[str] = set()
    assigned: set[tuple[int, int]] = set()
    result = []
    for field in fields:
        key = field.key.strip() or field_key(field.title)
        if key in keys:
            raise HTTPException(status_code=422, detail=f"Duplicate field key: {key}")
        keys.add(key)
        refs = []
        for ref in field.sources:
            table = available.get(ref.extract_id)
            if table is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Table #{ref.extract_id} is unavailable",
                )
            identity = (ref.extract_id, ref.column_index)
            if identity in assigned:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"A source column can belong to only one target field: #{ref.extract_id} "
                        f" {ref.column_index + 1}  columns"
                    ),
                )
            assigned.add(identity)
            versions = table["versions"]
            matching = (
                versions[0]
                if ref.mode == "auto"
                else next(
                    (
                        version
                        for version in versions
                        if version["stage"] == ref.stage and version["clean_id"] == ref.clean_id
                    ),
                    None,
                )
            )
            if matching is None or ref.column_index >= len(matching["headers"]):
                raise HTTPException(status_code=422, detail="Source version or column not found")
            if ref.mode == "fixed" and ref.source_hash != matching["hash"]:
                raise HTTPException(
                    status_code=409, detail="Fixed source file changed; link it again"
                )
            refs.append(ref.model_dump())
        result.append(
            {"key": key, "title": field.title.strip(), "scope": field.scope, "sources": refs}
        )
    return result


def _validated_table_settings(
    settings: dict[int, TableRule], tables: list[dict[str, object]], root: Path
) -> None:
    available = {int(table["extract_id"]): table for table in tables}
    for extract_id, rule in settings.items():
        table = available.get(extract_id)
        if table is None:
            raise HTTPException(
                status_code=422,
                detail=f"Table #{extract_id} is unavailable",
            )
        for version in table["versions"]:
            rows = _rows(root, version)
            if rule.header_row > len(rows):
                raise HTTPException(
                    status_code=422, detail=f"Table #{extract_id}  header row is out of range"
                )
            if not any(cell.strip() for cell in rows[rule.header_row - 1]):
                raise HTTPException(
                    status_code=422, detail=f"Table #{extract_id}  header row is empty"
                )
        max_rows = max(version["physical_row_count"] for version in table["versions"])
        if any(row > max_rows for row in rule.excluded_rows):
            raise HTTPException(
                status_code=422, detail=f"Table #{extract_id}  excluded row is out of range"
            )


def _build_output(
    fields: list[dict[str, object]], tables: list[dict[str, object]]
) -> tuple[bytes, str, int]:
    output = [PROVENANCE + [str(field["title"]) for field in fields] + ["source_cells_json"]]
    manifest: list[dict[str, object]] = []
    conflicts = 0
    for table in tables:
        table_refs = [
            (field_index, ref)
            for field_index, field in enumerate(fields)
            for ref in field["sources"]
            if ref["extract_id"] == table["extract_id"]
        ]
        resolved = []
        for field_index, ref in table_refs:
            variant = (
                table["versions"][0]
                if ref["mode"] == "auto"
                else next(
                    (
                        item
                        for item in table["versions"]
                        if item["stage"] == ref["stage"] and item["clean_id"] == ref["clean_id"]
                    ),
                    None,
                )
            )
            if variant is None or ref["column_index"] >= len(variant["headers"]):
                raise HTTPException(
                    status_code=409, detail="Mapped source version or column no longer exists"
                )
            if ref["mode"] == "fixed" and ref["source_hash"] != variant["hash"]:
                raise HTTPException(
                    status_code=409, detail="Fixed source file changed; link it again"
                )
            resolved.append((field_index, ref, variant))
        selected = resolved[0][2] if resolved else table["versions"][0]
        variants = list(
            {
                (variant["stage"], variant["clean_id"], variant["hash"]): variant
                for _, _, variant in resolved
            }.values()
        )
        if not variants:
            variants = [selected]
        row_count = max(
            len(_rows_from_version(variant)) + len(variant.get("deleted_rows", [])) - 1
            for variant in variants
        )
        positions = {id(variant): _source_index(variant) for variant in variants}
        deleted_everywhere = {
            row + 1 for variant in variants for row in variant.get("deleted_rows", [])
        }
        manifest.append(
            {
                "extract_id": table["extract_id"],
                "header_row": table.get("header_row", 1),
                "excluded_rows": table.get("excluded_rows", []),
                "extract_is_confirmed": table.get("extract_is_confirmed", False),
                "clean_is_confirmed": table.get("clean_is_confirmed", False),
                "sources": [
                    {
                        "column_index": ref["column_index"],
                        "stage": variant["stage"],
                        "clean_id": variant["clean_id"],
                        "hash": variant["hash"],
                    }
                    for _, ref, variant in resolved
                ],
                "fallback_hash": selected["hash"] if not resolved else None,
            }
        )
        header_row = int(table.get("header_row", 1))
        excluded_rows = set(table.get("excluded_rows", []))
        for row_index in range(header_row, row_count + 1):
            physical_row = row_index + 1
            if physical_row in excluded_rows or physical_row in deleted_everywhere:
                continue
            values: list[list[str]] = [[] for _ in fields]
            for field_index, ref, variant in resolved:
                rows = _rows_from_version(variant)
                position = positions[id(variant)].get(row_index)
                row = rows[position] if position is not None else []
                index = ref["column_index"]
                if index < len(row) and row[index].strip():
                    values[field_index].append(row[index])
            conflicts += sum(len(set(items)) > 1 for items in values)
            source_details = []
            for variant in variants:
                source_rows = _rows_from_version(variant)
                position = positions[id(variant)].get(row_index)
                query = {
                    "vnb": str(table["dso_slug"]),
                    "document": str(table["document_id"]),
                    "extract": str(table["extract_id"]),
                    "table_type": str(table.get("table_type", TABLE_TYPE_GRID_MEASURES)),
                    "view": "clean-review" if variant["clean_id"] else "review",
                    "header": "hidden",
                }
                if variant["clean_id"]:
                    query["clean"] = str(variant["clean_id"])
                source_details.append(
                    {
                        "stage": variant["stage"],
                        "clean_table_id": variant["clean_id"],
                        "file_path": variant.get("path"),
                        "file_hash": variant["hash"],
                        "row_number": physical_row,
                        "row_exists": position is not None,
                        "header_row": header_row,
                        "headers": variant["headers"],
                        "cells": source_rows[position] if position is not None else [],
                        "review_path": "/ui/overview?" + urlencode(query),
                        "bindings": [
                            {
                                "field": str(fields[index].get("key") or fields[index]["title"]),
                                "column_number": ref["column_index"] + 1,
                            }
                            for index, ref, source in resolved
                            if source is variant
                        ],
                    }
                )
            provenance = {
                "schema_version": OUTPUT_SCHEMA_VERSION,
                "origin": {
                    "dso_slug": table["dso_slug"],
                    "document_id": table["document_id"],
                    "document_title": table.get("document_title"),
                    "extract_table_id": table["extract_id"],
                    "extraction_tool": table.get("tool"),
                    "table_number": table.get("table_number"),
                    "row_number": physical_row,
                    "extract_is_confirmed": bool(table.get("extract_is_confirmed", False)),
                    "clean_is_confirmed": bool(table.get("clean_is_confirmed", False)),
                },
                "sources": source_details,
            }
            output.append(
                [
                    str(table["dso_slug"]),
                    *(
                        _json(list(dict.fromkeys(items)))
                        if len(set(items)) > 1
                        else (items[0] if items else "")
                        for items in values
                    ),
                    _json(provenance),
                ]
            )
    fingerprint = hashlib.sha256(
        _json(
            {"output_schema_version": OUTPUT_SCHEMA_VERSION, "fields": fields, "sources": manifest}
        ).encode()
    ).hexdigest()
    return csv_content(output), fingerprint, conflicts


def _rows_from_version(version: dict[str, object]) -> list[list[str]]:
    return version["rows"]  # type: ignore[return-value]


@contextmanager
def _replace_output(root: Path, relative: str, content: bytes) -> Iterator[None]:
    """Publish a complete output, restoring the previous file if the DB commit fails."""
    destination = resolve_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".output-", dir=destination.parent) as temporary:
        pending = Path(temporary) / "pending"
        backup = Path(temporary) / "previous"
        existed = destination.exists()
        if existed:
            shutil.copyfile(destination, backup)
        pending.write_bytes(content)
        pending.replace(destination)
        try:
            yield
        except BaseException:
            if existed:
                backup.replace(destination)
            else:
                destination.unlink(missing_ok=True)
            raise


def router(root: Path) -> APIRouter:
    """Create routes for the dedicated harmonization workspace.

    Args:
        root: Data repository containing SQLite and CSV files.

    Returns:
        API router.
    """
    api = APIRouter(prefix="/api/harmonize", tags=["harmonize"])

    @api.get("/schemes")
    def schemes() -> list[dict[str, object]]:
        with connect(root / "nap_tool.sqlite") as connection:
            return [
                _summary(row, connection)
                for row in connection.execute("SELECT * FROM harmonize_scheme ORDER BY id")
            ]

    @api.get("/inventory")
    def inventory(
        scheme_id: int | None = None, set_id: int | None = Query(default=None, gt=0)
    ) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            scheme = _scheme(connection, scheme_id) if scheme_id else None
            settings = _table_settings(scheme) if scheme is not None else {}
            tables = _inventory(
                connection,
                root,
                settings,
                table_type=None,
            )
            effective_set = set_id or (scheme["initial_set_id"] if scheme is not None else None)
            members = (
                _set_member_ids(connection, effective_set) if effective_set is not None else None
            )
        for table in tables:
            table["in_set"] = members is None or table["extract_id"] in members
            for version in table["versions"]:
                version.pop("path")
        return {"tables": tables, "table_count": len(tables)}

    @api.get("/schemes/{scheme_id}")
    def get_scheme(
        scheme_id: int, set_id: int | None = Query(default=None, gt=0)
    ) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            scheme = _scheme(connection, scheme_id)
            settings = _table_settings(scheme)
            fields = _fields(connection, scheme, [])
            summary = _summary(scheme, connection)
            effective_set = set_id if set_id is not None else scheme["initial_set_id"]
            if effective_set is not None:
                summary.update(_pair_summary(connection, root, scheme, effective_set))
            return {
                **summary,
                "fields": fields,
                "table_settings": {
                    str(extract_id): rule.model_dump() for extract_id, rule in settings.items()
                },
            }

    @api.post("/schemes", status_code=201)
    def create_scheme(request: NewScheme) -> dict[str, object]:
        mode = request.creation_mode or ("copy" if request.copy_from_id is not None else "blank")
        if (mode == "copy") != (request.copy_from_id is not None):
            raise HTTPException(status_code=422, detail="Choose a source scheme only for copy mode")
        with connect(root / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            slug = _new_slug(connection, request.name.strip())
            source = _scheme(connection, request.copy_from_id) if request.copy_from_id else None
            _validate_initial_set(connection, request.initial_set_id)
            selected = connection.execute(
                "SELECT table_type_id FROM harmonize_set WHERE id=?", (request.initial_set_id,)
            ).fetchone()
            table_type = selected["table_type_id"] if selected is not None else None
            source_settings = (
                _table_settings(source)
                if source is not None
                else _selected_clean_header_settings(connection, table_type)
            )
            source_tables = (
                _inventory(connection, root, source_settings, table_type=table_type)
                if mode in ("lcs80", "lcs60")
                else []
            )
            source_fields = (
                _fields(connection, source, source_tables)
                if source is not None
                else _lcs_fields(mode, source_tables)
                if mode in ("lcs80", "lcs60")
                else []
            )
            stamp = _now()
            cursor = connection.execute(
                "INSERT INTO harmonize_scheme(name,slug,initial_set_id,copy_from_scheme_id,"
                "table_settings,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    request.name.strip(),
                    slug,
                    request.initial_set_id,
                    request.copy_from_id,
                    _json({str(key): rule.model_dump() for key, rule in source_settings.items()}),
                    stamp,
                    stamp,
                ),
            )
            new_id = cursor.lastrowid
            _insert_fields(connection, new_id, source_fields, stamp)
            return {"id": new_id, "name": request.name.strip()}

    @api.put("/schemes/{scheme_id}/initial-set")
    def update_scheme_initial_set(
        scheme_id: int, request: SchemeInitialSetUpdate
    ) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            scheme = _scheme(connection, scheme_id)
            if scheme["updated_at"] != request.expected_updated_at:
                raise HTTPException(status_code=409, detail="Scheme changed; reload before saving")
            _validate_initial_set(connection, request.initial_set_id)
            connection.execute(
                "UPDATE harmonize_scheme SET initial_set_id=?,updated_at=? WHERE id=?",
                (request.initial_set_id, _now(), scheme_id),
            )
            return _summary(_scheme(connection, scheme_id), connection)

    @api.put("/schemes/{scheme_id}")
    def update_scheme(scheme_id: int, request: SchemeUpdate) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            scheme = _scheme(connection, scheme_id)
            if scheme["updated_at"] != request.expected_updated_at:
                raise HTTPException(status_code=409, detail="Scheme changed; refresh before saving")
            if request.name.strip() != scheme["name"]:
                raise HTTPException(status_code=422, detail="Scheme name cannot be changed")
            settings = (
                request.table_settings
                if request.table_settings is not None
                else _table_settings(scheme)
            )
            _validated_table_settings(settings, _inventory(connection, root, table_type=None), root)
            fields = _validated_fields(
                request.fields,
                _inventory(connection, root, settings, table_type=None),
            )
            stamp = _now()
            connection.execute("DELETE FROM harmonize_field WHERE scheme_id=?", (scheme_id,))
            _insert_fields(connection, scheme_id, fields, stamp)
            connection.execute(
                "UPDATE harmonize_scheme SET table_settings=?,updated_at=? WHERE id=?",
                (
                    _json({str(key): rule.model_dump() for key, rule in settings.items()}),
                    stamp,
                    scheme_id,
                ),
            )
            return {"id": scheme_id, "updated_at": stamp}

    @api.delete("/schemes/{scheme_id}")
    def delete_scheme(scheme_id: int) -> dict[str, bool | int]:
        with connect(root / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            _scheme(connection, scheme_id)
            if connection.execute(
                "SELECT 1 FROM harmonize_set WHERE current_scheme_id=?", (scheme_id,)
            ).fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="Scheme is the default of a Set; change its default before deleting",
                )
            paths = [
                row[0]
                for row in connection.execute(
                    "SELECT output_path FROM harmonize_set_output WHERE scheme_id=?", (scheme_id,)
                )
            ]
            deleted_fields = connection.execute(
                "DELETE FROM harmonize_field WHERE scheme_id=?", (scheme_id,)
            ).rowcount
            connection.execute(
                "UPDATE harmonize_scheme SET copy_from_scheme_id=NULL WHERE copy_from_scheme_id=?",
                (scheme_id,),
            )
            connection.execute("DELETE FROM harmonize_scheme WHERE id=?", (scheme_id,))
        for path in paths:
            if not re.fullmatch(r"harmonized/scheme_\d+/(?:output|[0-9a-f]{64})\.csv", path):
                resolve_path(root, path).unlink(missing_ok=True)
        return {"deleted": True, "deleted_fields": deleted_fields}

    @api.post("/schemes/{scheme_id}/generate")
    def generate(
        scheme_id: int, set_id: int | None = Query(default=None, gt=0)
    ) -> dict[str, object]:
        # Keep the file rollback context alive until the database has committed.
        with ExitStack() as outputs, connect(root / "nap_tool.sqlite") as connection:
            # Finish any schema upgrade before acquiring the generation write lock.
            connection.commit()
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            scheme = _scheme(connection, scheme_id)
            effective_set = set_id if set_id is not None else scheme["initial_set_id"]
            if effective_set is None:
                raise HTTPException(
                    status_code=422, detail="Choose a Set before generating results"
                )
            tables = _pair_tables(connection, root, scheme, effective_set)
            if not tables:
                raise HTTPException(status_code=422, detail="Set has no tables")
            fields = _fields(connection, scheme, tables)
            if not fields:
                raise HTTPException(status_code=422, detail="Scheme has no target fields")
            for table in tables:
                for version in table["versions"]:
                    version["rows"] = _rows(root, version)
            content, manifest_hash, conflicts = _build_output(fields, tables)
            digest = hashlib.sha256(content).hexdigest()
            selected_set = connection.execute(
                "SELECT slug FROM harmonize_set WHERE id=?", (effective_set,)
            ).fetchone()
            slug = scheme["slug"] or f"scheme_{scheme_id}"
            relative = f"harmonized/{selected_set['slug']}/{slug}.csv"
            # Keep the existing source-details JSON alongside the six provenance columns.
            rows = csv_rows(content)
            rows[0][1:1] = [
                "nap_year",
                "document_key",
                "extractor",
                "table_number",
                "row_number",
            ]
            by_id = {table["extract_id"]: table for table in tables}
            for row in rows[1:]:
                origin = json.loads(row[-1])["origin"]
                table = by_id[origin["extract_table_id"]]
                row[1:1] = [
                    str(table["nap_year"] or ""),
                    str(table["document_key"]),
                    str(table["tool"]),
                    str(table["table_number"]),
                    str(origin["row_number"]),
                ]
            content = csv_content(rows)
            digest = hashlib.sha256(content).hexdigest()
            manifest_hash = _pair_manifest(fields, tables)
            outputs.enter_context(_replace_output(root, relative, content))
            connection.execute(
                "INSERT INTO harmonize_set_output VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(set_id,scheme_id) DO UPDATE SET output_path=excluded.output_path,"
                "output_hash=excluded.output_hash,source_manifest_hash=excluded.source_manifest_hash,"
                "generated_at=excluded.generated_at",
                (effective_set, scheme_id, relative, digest, manifest_hash, _now()),
            )
        return {
            "rows": len(csv_rows(content)) - 1,
            "tables": len(tables),
            "fields": len(fields),
            "conflicts": conflicts,
            "hash": digest,
        }

    @api.get("/schemes/{scheme_id}/preview")
    def preview(
        scheme_id: int,
        set_id: int | None = Query(default=None, gt=0),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=30, ge=1, le=100),
    ) -> dict[str, object]:
        with connect(root / "nap_tool.sqlite") as connection:
            scheme = _scheme(connection, scheme_id)
            effective_set = set_id if set_id is not None else scheme["initial_set_id"]
            if effective_set is None:
                raise HTTPException(status_code=422, detail="Choose a Set to view results")
            if effective_set is not None:
                _validate_initial_set(connection, effective_set)
                scheme = connection.execute(
                    "SELECT * FROM harmonize_set_output WHERE set_id=? AND scheme_id=?",
                    (effective_set, scheme_id),
                ).fetchone()
        if scheme is None or not scheme["output_path"]:
            raise HTTPException(status_code=404, detail="Generate a harmonized table first")
        variant = {"path": scheme["output_path"], "hash": scheme["output_hash"]}
        rows = _rows(root, variant)
        start = (page - 1) * page_size
        return {
            "header": rows[0] if rows else [],
            "rows": rows[1 + start : 1 + start + page_size],
            "total_rows": max(0, len(rows) - 1),
            "page": page,
            "page_size": page_size,
        }

    @api.get("/schemes/{scheme_id}/download")
    def download(scheme_id: int, set_id: int | None = Query(default=None, gt=0)) -> FileResponse:
        with connect(root / "nap_tool.sqlite") as connection:
            scheme = _scheme(connection, scheme_id)
            effective_set = set_id if set_id is not None else scheme["initial_set_id"]
            if effective_set is None:
                raise HTTPException(status_code=422, detail="Choose a Set to view results")
            if effective_set is not None:
                _validate_initial_set(connection, effective_set)
                scheme = connection.execute(
                    "SELECT * FROM harmonize_set_output WHERE set_id=? AND scheme_id=?",
                    (effective_set, scheme_id),
                ).fetchone()
        if scheme is None or not scheme["output_path"]:
            raise HTTPException(status_code=404, detail="Generate a harmonized table first")
        try:
            path = checked_file(root, scheme["output_path"], scheme["output_hash"])
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        filename = f"{path.parent.name}_{path.name}"
        return FileResponse(path, media_type="text/csv", filename=filename)

    return api
