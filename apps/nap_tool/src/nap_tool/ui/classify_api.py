# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Thin UI adapter for the same classifier used by the CLI."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from nap_tool.classifier.rules import DERIVED_FIELDS, LIST_SEPARATOR
from nap_tool.classifier.service import OUTPUT_FILES, output_status, run, saved_output


def row_dsos(row: dict[str, str]) -> set[str]:
    """Return the grid operators of a classified row or of an unmapped-value row.

    Args:
        row: A row from ``classified.csv`` (``dso_slug``) or ``unmapped_values.csv``
            (comma-separated ``dso_slugs``; semicolons in outputs saved before 2026-11).

    Returns:
        The non-empty grid operator slugs of the row.
    """
    slugs = (row.get("dso_slug") or row.get("dso_slugs", "")).replace(";", LIST_SEPARATOR)
    return {slug for slug in slugs.split(LIST_SEPARATOR) if slug}


def router(root: Path) -> APIRouter:
    api = APIRouter(prefix="/api/classify", tags=["classify"])

    @api.get("/schemes/{scheme_id}")
    def status(scheme_id: int, set_id: int | None = Query(None, gt=0)) -> dict:
        try:
            return output_status(root, scheme_id, set_id=set_id)
        except (ValueError, RuntimeError, OSError) as error:
            raise HTTPException(409, str(error)) from error

    @api.post("/schemes/{scheme_id}/run")
    def generate(scheme_id: int, set_id: int | None = Query(None, gt=0)) -> dict:
        try:
            result = run(root, scheme_id, set_id=set_id)
            return dict(report=result.report)
        except (ValueError, RuntimeError, OSError) as error:
            raise HTTPException(409, str(error)) from error

    @api.get("/schemes/{scheme_id}/preview")
    def preview(
        scheme_id: int,
        set_id: int | None = Query(None, gt=0),
        page: int = Query(1, ge=1),
        page_size: int = Query(100, ge=1, le=100),
        q: str = "",
        dso: str = "",
        record_type: str = "",
        asset_type: str = "",
        measure_type: str = "",
        flag: str = "",
        field: str = "",
        value: str = "",
        view: str = "data",
    ) -> dict:
        try:
            directory, _ = saved_output(root, scheme_id, set_id=set_id)
            filename = "unmapped_values.csv" if view == "unmapped" else "classified.csv"
            with (directory / filename).open(encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                headers = reader.fieldnames or []
                rows = list(reader)
        except FileNotFoundError as error:
            raise HTTPException(404, "Run classification first") from error
        except (ValueError, RuntimeError, OSError) as error:
            raise HTTPException(409, str(error)) from error
        options = {
            column: sorted({row.get(column, "") for row in rows if row.get(column)})
            for column in [
                "inferred_record_type",
                "inferred_asset_type",
                "inferred_measure_type",
                "field",
            ]
        }
        options["dso"] = sorted({slug for row in rows for slug in row_dsos(row)})
        options["inferred_flags"] = sorted(
            {
                item
                for row in rows
                for item in row.get("inferred_flags", "").split(LIST_SEPARATOR)
                if item
            }
        )
        selected = [
            row
            for row in rows
            if (not q or q.casefold() in json.dumps(row, ensure_ascii=False).casefold())
            and (not dso or dso in row_dsos(row))
            and (not record_type or row.get("inferred_record_type") == record_type)
            and (not asset_type or row.get("inferred_asset_type") == asset_type)
            and (not measure_type or row.get("inferred_measure_type") == measure_type)
            and (not flag or flag in row.get("inferred_flags", "").split(LIST_SEPARATOR))
            and (not field or row.get("field") == field)
            and (not value or value.casefold() in row.get("value", "").casefold())
        ]
        start = (page - 1) * page_size
        return dict(
            header=headers,
            derived=[name for name in headers if name in DERIVED_FIELDS],
            rows=[[row[key] for key in headers] for row in selected[start : start + page_size]],
            total_rows=len(selected),
            page=page,
            page_size=page_size,
            options=options,
        )

    @api.get("/schemes/{scheme_id}/download/{filename}")
    def download(
        scheme_id: int, filename: str, set_id: int | None = Query(None, gt=0)
    ) -> FileResponse:
        if filename not in OUTPUT_FILES:
            raise HTTPException(404, "Unknown classification output")
        try:
            directory, _ = saved_output(root, scheme_id, set_id=set_id)
        except FileNotFoundError as error:
            raise HTTPException(404, "Run classification first") from error
        except (ValueError, RuntimeError, OSError) as error:
            raise HTTPException(409, str(error)) from error
        return FileResponse(directory / filename, filename=filename)

    return api
