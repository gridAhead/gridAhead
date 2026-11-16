# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI backend for the overview and extraction review workspace."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nap_tool.data import checked_file, data_dir, write_bytes
from nap_tool.database.schema import (
    TABLE_TYPE_GRID_MEASURES,
    DatabaseVersionError,
    connect,
    require_version,
)
from nap_tool.ui.classify_api import router as classify_router
from nap_tool.ui.clean_api import install_clean_routes
from nap_tool.ui.harmonize_api import router as harmonize_router
from nap_tool.ui.sets_api import router as sets_router

STATIC_DIR = Path(__file__).parent / "static"


class ExtractReviewUpdate(BaseModel):
    """A reviewed CSV grid with hashes for optimistic concurrency."""

    rows: list[list[str]] = Field(min_length=1)
    source_hash: str
    reviewed_hash: str | None = None
    confirm: bool = False


class ExtractReviewMetadataUpdate(BaseModel):
    """One change to a table's review classification or note."""

    source_hash: str
    reviewed_hash: str | None = None
    table_type: int | None = Field(default=None, gt=0)
    is_archived: bool | None = None
    note: str | None = Field(default=None, max_length=5000)


class TableTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class DocumentYearUpdate(BaseModel):
    nap_year: int | None = Field(ge=2000, le=2100, strict=True)
    expected_updated_at: str


class CompactSheetUpdate(BaseModel):
    is_compact_sheet: bool
    expected_updated_at: str


class DsoIdentifiersUpdate(BaseModel):
    """Official identifiers for one electricity network operator."""

    mastr_nr: str | None = Field(default=None, max_length=64)
    bdew_code: str | None = Field(default=None, max_length=64)


def _review_record(connection: sqlite3.Connection, extract_id: int) -> sqlite3.Row:
    """Load the extraction and its source document or raise 404."""
    row = connection.execute(
        "SELECT e.id, e.tool, e.table_number, e.pages, e.regions, e.extract_table_hash, "
        "e.extract_table_path, e.extract_reviewed_table_hash, "
        "e.extract_reviewed_table_path, e.extract_is_confirmed, "
        "et.table_type_id AS table_type, e.extract_is_archived, e.extract_reviewed_table_notes, "
        "e.extract_reviewed_source_hash, d.file_path AS document_path, "
        "d.hash AS document_hash, d.title AS document_title "
        "FROM extract_table e LEFT JOIN extract_table_type et ON et.extract_table_id=e.id "
        "JOIN document d ON d.id=e.document_id WHERE e.id=?",
        (extract_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Extracted table not found")
    return row


SPREADSHEET_MEDIA_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xls": "application/vnd.ms-excel",
}


TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def _file_type(relative: str | None) -> str | None:
    """File type of a stored document, such as "pdf" or "xlsx"; None if not downloaded."""
    if not relative:
        return None
    return Path(relative).suffix.lstrip(".").lower() or None


def _verified_file(root: Path, relative: str | None, digest: str | None) -> Path:
    """Resolve a database file only when it exists and matches its hash."""
    if relative is None or digest is None:
        raise HTTPException(status_code=404, detail="File does not exist")
    try:
        return checked_file(root, relative, digest)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@contextmanager
def _read_database(root: Path) -> Iterator[sqlite3.Connection]:
    database = root / "nap_tool.sqlite"
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        require_version(connection, database)
        yield connection
    finally:
        connection.close()


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.reader(source))


def _first_page(pages_json: str) -> int | None:
    pages = json.loads(pages_json)
    return int(pages[0]) if isinstance(pages, list) and pages else None


def create_app(root: Path | None = None) -> FastAPI:
    """Create the overview and extraction review application.

    Args:
        root: Data repository root; uses NAP_DATA_DIR when omitted.

    Returns:
        Configured FastAPI application.

    Raises:
        RuntimeError: If data or built frontend files are missing, or the database
            version differs from DB_VERSION.
    """
    repository = root if root is not None else data_dir()
    database = repository / "nap_tool.sqlite"
    if not database.is_file():
        raise RuntimeError(f"Metadata database not found: {database}")
    # Read-write so SQLite can roll back a crashed write's journal; never creates tables.
    with closing(sqlite3.connect(database)) as connection:
        require_version(connection, database)
    if not (STATIC_DIR / "index.html").is_file():
        raise RuntimeError(
            "UI build is missing; run `pnpm --filter nap-tool-ui build` in the gridAhead repo root"
        )

    app = FastAPI(title="NAP Tool overview", docs_url="/api/docs", redoc_url=None)
    app.mount("/ui/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.exception_handler(DatabaseVersionError)
    def database_version_error(request: Request, error: DatabaseVersionError) -> JSONResponse:
        """Report a nap_data version change found after startup to the browser.

        Args:
            request: Request that opened the database.
            error: Version mismatch with the update hint.

        Returns:
            Conflict response whose detail the frontend displays.
        """
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.get("/", include_in_schema=False)
    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/", include_in_schema=False)
    def ui_root() -> RedirectResponse:
        """Redirect to the overview page.

        Returns:
            Redirect response.
        """
        return RedirectResponse("/ui/overview")

    @app.get("/ui/overview", include_in_schema=False)
    @app.get("/ui/harmonize", include_in_schema=False)
    @app.get("/ui/harmonize/sets", include_in_schema=False)
    @app.get("/ui/harmonize/result", include_in_schema=False)
    @app.get("/ui/classify", include_in_schema=False)
    @app.get("/ui/settings", include_in_schema=False)
    @app.get("/ui/schema", include_in_schema=False)
    def overview_page() -> FileResponse:
        """Serve the React application.

        Returns:
            Built HTML entry point.
        """
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/table-types")
    def table_types() -> list[dict[str, object]]:
        """List classification types and their usage."""
        with _read_database(repository) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT t.*, (SELECT COUNT(*) FROM extract_table_type e "
                    "WHERE e.table_type_id=t.id) "
                    "AS table_count, (SELECT COUNT(*) FROM harmonize_set s "
                    "WHERE s.table_type_id=t.id) AS set_count FROM table_type t ORDER BY t.id"
                )
            ]

    @app.post("/api/table-types", status_code=201)
    def create_table_type(request: TableTypeCreate) -> dict[str, object]:
        """Create a named table type."""
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name is required")
        with connect(repository / "nap_tool.sqlite") as connection:
            try:
                cursor = connection.execute("INSERT INTO table_type(name) VALUES (?)", (name,))
            except sqlite3.IntegrityError as error:
                raise HTTPException(
                    status_code=409, detail="Table type name already exists"
                ) from error
            return {
                "id": cursor.lastrowid,
                "name": name,
                "table_count": 0,
                "set_count": 0,
            }

    @app.delete("/api/table-types/{type_id}")
    def delete_table_type(type_id: int) -> dict[str, bool]:
        """Delete an unused table type."""
        with connect(repository / "nap_tool.sqlite") as connection:
            if (
                connection.execute("SELECT 1 FROM table_type WHERE id=?", (type_id,)).fetchone()
                is None
            ):
                raise HTTPException(status_code=404, detail="Table type not found")
            try:
                connection.execute("DELETE FROM table_type WHERE id=?", (type_id,))
            except sqlite3.IntegrityError as error:
                raise HTTPException(
                    status_code=409, detail="Table type is used by tables, schemes or sets"
                ) from error
        return {"deleted": True}

    @app.get("/api/schema")
    def database_schema() -> dict[str, object]:
        """Describe the current pipeline tables and their relationships.

        Returns:
            Column metadata, row counts, foreign keys, and JSON source mappings.
        """
        table_names = (
            "download_run",
            "dso",
            "document",
            "extract_table",
            "table_type",
            "extract_table_type",
            "clean_table",
            "harmonize_scheme",
            "harmonize_set",
            "harmonize_set_output",
            "harmonize_field",
            "harmonize_field_source",
        )
        tables: list[dict[str, object]] = []
        relations: list[dict[str, str]] = []
        with _read_database(repository) as connection:
            for table_name in table_names:
                columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                foreign_keys = connection.execute(
                    f"PRAGMA foreign_key_list({table_name})"
                ).fetchall()
                foreign_key_columns = {key["from"] for key in foreign_keys}
                row_count = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                tables.append(
                    {
                        "name": table_name,
                        "row_count": row_count,
                        "columns": [
                            {
                                "name": column["name"],
                                "type": column["type"],
                                "is_primary_key": bool(column["pk"]),
                                "is_foreign_key": column["name"] in foreign_key_columns,
                                "is_nullable": not bool(column["notnull"] or column["pk"]),
                            }
                            for column in columns
                        ],
                    }
                )
                relations.extend(
                    {
                        "from_table": key["table"],
                        "from_column": key["to"],
                        "to_table": table_name,
                        "to_column": key["from"],
                        "kind": "foreign_key",
                    }
                    for key in foreign_keys
                )
        return {"tables": tables, "relations": relations}

    @app.get("/api/overview/summary")
    def summary() -> dict[str, int]:
        """Return stage totals for the header.

        Returns:
            Counts by stage.
        """
        with _read_database(repository) as connection:
            return {
                "vnbs": connection.execute("SELECT COUNT(*) FROM dso").fetchone()[0],
                "documents": connection.execute("SELECT COUNT(*) FROM document").fetchone()[0],
                "downloaded": connection.execute(
                    "SELECT COUNT(*) FROM document WHERE file_path IS NOT NULL"
                ).fetchone()[0],
                "extracted": connection.execute("SELECT COUNT(*) FROM extract_table").fetchone()[0],
                "measures": connection.execute(
                    "SELECT COUNT(*) FROM extract_table_type WHERE table_type_id=?",
                    (TABLE_TYPE_GRID_MEASURES,),
                ).fetchone()[0],
                "cleaned": connection.execute("SELECT COUNT(*) FROM clean_table").fetchone()[0],
            }

    @app.get("/api/overview/dsos")
    @app.get("/api/overview/vnbs", include_in_schema=False)
    def vnbs() -> list[dict[str, object]]:
        """Return VNB summaries for the first column.

        Returns:
            VNB records and document counts.
        """
        with _read_database(repository) as connection:
            rows = connection.execute(
                "SELECT v.id, v.name, v.slug, v.mastr_nr, v.bdew_code, "
                "(SELECT COUNT(*) FROM document d WHERE d.dso_id=v.id) AS document_count, "
                "(SELECT COUNT(*) FROM document d WHERE d.dso_id=v.id "
                "AND d.file_path IS NOT NULL) AS downloaded_count "
                "FROM dso v ORDER BY v.name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    @app.patch("/api/overview/dsos/{dso_id}/identifiers")
    def update_dso_identifiers(dso_id: int, request: DsoIdentifiersUpdate) -> dict[str, object]:
        """Set verified official identifiers; empty values clear a field."""
        with connect(repository / "nap_tool.sqlite") as connection:
            record = connection.execute("SELECT id FROM dso WHERE id=?", (dso_id,)).fetchone()
            if record is None:
                raise HTTPException(status_code=404, detail="DSO not found")
            mastr_nr = (request.mastr_nr or "").strip() or None
            bdew_code = (request.bdew_code or "").strip() or None
            connection.execute(
                "UPDATE dso SET mastr_nr=?, bdew_code=?, updated_at=? WHERE id=?",
                (mastr_nr, bdew_code, datetime.now(timezone.utc).isoformat(), dso_id),
            )
            row = connection.execute(
                "SELECT id, name, slug, mastr_nr, bdew_code FROM dso WHERE id=?", (dso_id,)
            ).fetchone()
        return dict(row)

    @app.get("/api/overview/documents")
    def documents(
        vnb: str | None = Query(default=None, min_length=1),
        year: int | None = Query(default=None, ge=2000, le=2100),
    ) -> list[dict[str, object]]:
        """Return documents across VNBs, optionally filtered by VNB and NAP year.

        Args:
            vnb: Optional VNB slug.
            year: Optional NAP report year.

        Returns:
            Document summaries.
        """
        with _read_database(repository) as connection:
            if (
                vnb is not None
                and connection.execute("SELECT 1 FROM dso WHERE slug=?", (vnb,)).fetchone() is None
            ):
                raise HTTPException(status_code=404, detail="DSO not found")
            rows = connection.execute(
                "SELECT d.id, d.title, d.version, d.nap_year, d.source, d.is_selected, "
                "d.is_compact_sheet, d.file_path IS NOT NULL AS is_downloaded, d.file_path, "
                "d.created_at, d.updated_at, "
                "v.slug AS dso_slug, v.name AS vnb_name, "
                "(SELECT COUNT(*) FROM extract_table e WHERE e.document_id=d.id) "
                "AS extract_count "
                "FROM document d JOIN dso v ON v.id=d.dso_id "
                "WHERE (? IS NULL OR v.slug=?) "
                "ORDER BY d.is_selected DESC, d.id DESC",
                (vnb, vnb),
            ).fetchall()
        summaries = [
            {
                **{key: row[key] for key in row.keys() if key != "file_path"},
                "year": row["nap_year"],
                "file_type": _file_type(row["file_path"]),
            }
            for row in rows
        ]
        return [item for item in summaries if year is None or item["year"] == year]

    @app.patch("/api/overview/documents/{document_id}/year")
    def update_document_year(document_id: int, request: DocumentYearUpdate) -> dict[str, object]:
        with connect(repository / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT updated_at FROM document WHERE id=?", (document_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Document not found")
            if row["updated_at"] != request.expected_updated_at:
                raise HTTPException(
                    status_code=409, detail="Document changed; reload before saving"
                )
            stamp = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE document SET nap_year=?,updated_at=? WHERE id=?",
                (request.nap_year, stamp, document_id),
            )
        return {"id": document_id, "year": request.nap_year, "updated_at": stamp}

    @app.patch("/api/overview/documents/{document_id}/compact-sheet")
    def update_document_compact_sheet(
        document_id: int, request: CompactSheetUpdate
    ) -> dict[str, object]:
        """Mark or unmark a document as its DSO's compact sheet for its NAP round.

        Marking replaces the DSO's previous compact sheet of the same round.
        """
        with connect(repository / "nap_tool.sqlite") as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT dso_id, nap_year, file_path, updated_at FROM document WHERE id=?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Document not found")
            if row["updated_at"] != request.expected_updated_at:
                raise HTTPException(
                    status_code=409, detail="Document changed; reload before saving"
                )
            if request.is_compact_sheet and (
                row["nap_year"] is None or _file_type(row["file_path"]) != "xlsx"
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Only an XLSX document with a NAP round can be a compact sheet",
                )
            stamp = datetime.now(timezone.utc).isoformat()
            if request.is_compact_sheet:
                connection.execute(
                    "UPDATE document SET is_compact_sheet=0, updated_at=? "
                    "WHERE dso_id=? AND nap_year=? AND is_compact_sheet=1 AND id<>?",
                    (stamp, row["dso_id"], row["nap_year"], document_id),
                )
            connection.execute(
                "UPDATE document SET is_compact_sheet=?, updated_at=? WHERE id=?",
                (int(request.is_compact_sheet), stamp, document_id),
            )
        return {
            "id": document_id,
            "is_compact_sheet": request.is_compact_sheet,
            "updated_at": stamp,
        }

    @app.get("/api/overview/documents/{document_id}/pdf")
    def document_pdf(document_id: int) -> FileResponse:
        """Open a document's verified source PDF inline.

        Args:
            document_id: Document ID.

        Returns:
            Inline PDF response.

        Raises:
            HTTPException: If the document or verified PDF is unavailable.
        """
        with _read_database(repository) as connection:
            row = connection.execute(
                "SELECT file_path, hash FROM document WHERE id=?", (document_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if not (row["file_path"] or "").endswith(".pdf"):
            raise HTTPException(status_code=404, detail="Document is not a PDF")
        path = _verified_file(repository, row["file_path"], row["hash"])
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    @app.get("/api/overview/documents/{document_id}/table")
    def document_table(document_id: int) -> FileResponse:
        """Download a document's verified source spreadsheet (XLSX).

        Args:
            document_id: Document ID.

        Returns:
            Spreadsheet download named after the document title.

        Raises:
            HTTPException: If the document or verified spreadsheet is unavailable.
        """
        with _read_database(repository) as connection:
            row = connection.execute(
                "SELECT title, file_path, hash FROM document WHERE id=?", (document_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        suffix = Path(row["file_path"] or "").suffix.lower()
        if suffix not in SPREADSHEET_MEDIA_TYPES:
            raise HTTPException(status_code=404, detail="Document is not a spreadsheet")
        path = _verified_file(repository, row["file_path"], row["hash"])
        title = row["title"].strip() or f"document_{document_id}"
        filename = title if title.lower().endswith(suffix) else f"{title}{suffix}"
        return FileResponse(path, media_type=SPREADSHEET_MEDIA_TYPES[suffix], filename=filename)

    @app.get("/api/overview/documents/{document_id}/text")
    def document_text(document_id: int) -> FileResponse:
        """Open a document's verified Markdown or text source inline in the browser.

        Served as UTF-8 plain text, so the browser shows the source instead of
        downloading it.

        Args:
            document_id: Document ID.

        Returns:
            Inline plain-text response.

        Raises:
            HTTPException: If the document or verified text file is unavailable.
        """
        with _read_database(repository) as connection:
            row = connection.execute(
                "SELECT file_path, hash FROM document WHERE id=?", (document_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if Path(row["file_path"] or "").suffix.lower() not in TEXT_SUFFIXES:
            raise HTTPException(status_code=404, detail="Document is not a text file")
        path = _verified_file(repository, row["file_path"], row["hash"])
        return FileResponse(
            path, media_type="text/plain; charset=utf-8", content_disposition_type="inline"
        )

    @app.get("/api/overview/extract-tables")
    def extract_tables(
        document_id: int | None = Query(default=None, gt=0),
        tool: Literal["all", "docling", "llmPDF"] = "all",
        table_type: str = "all",
        measures: Literal["all", "yes", "no"] = "all",
    ) -> list[dict[str, object]]:
        """Return extracted tables for a document and filters.

        Args:
            document_id: Optional source document ID; omitted returns all extractions.
            tool: Extraction tool filter.
            table_type: Table classification filter.
            measures: Legacy measure table filter.

        Returns:
            Extracted table summaries.
        """
        query = (
            "SELECT e.id, e.document_id, e.tool, e.table_number, e.pages, "
            "e.is_selected, et.table_type_id AS table_type, e.extract_is_confirmed, "
            "e.extract_is_archived, e.extract_reviewed_source_hash, "
            "e.extract_reviewed_table_path, "
            "e.extract_table_hash, e.extract_created_at, e.extract_table_notes, "
            "d.title AS document_title, v.slug AS dso_slug, v.name AS vnb_name, "
            "(SELECT COUNT(*) FROM clean_table c WHERE c.extract_table_id=e.id) AS clean_count "
            "FROM extract_table e LEFT JOIN extract_table_type et ON et.extract_table_id=e.id "
            "JOIN document d ON d.id=e.document_id "
            "JOIN dso v ON v.id=d.dso_id WHERE 1=1"
        )
        parameters: list[str | int] = []
        if document_id is not None:
            query += " AND e.document_id=?"
            parameters.append(document_id)
        if tool != "all":
            query += " AND e.tool=?"
            parameters.append(tool)
        if table_type == "all" and measures != "all":
            table_type = "1" if measures == "yes" else "non_measures"
        if table_type == "unclassified":
            query += " AND et.table_type_id IS NULL"
        elif table_type == "non_measures":
            query += " AND (et.table_type_id IS NULL OR et.table_type_id!=1)"
        elif table_type != "all":
            query += " AND et.table_type_id=?"
            if not table_type.isdecimal() or int(table_type) < 1:
                raise HTTPException(status_code=422, detail="Invalid table type filter")
            parameters.append(int(table_type))
        query += " ORDER BY e.extract_is_archived, v.name, d.id, e.table_number, e.tool, e.id"
        with _read_database(repository) as connection:
            if document_id is not None:
                document_exists = connection.execute(
                    "SELECT 1 FROM document WHERE id=?", (document_id,)
                ).fetchone()
                if document_exists is None:
                    raise HTTPException(status_code=404, detail="Document not found")
            rows = connection.execute(query, parameters).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            notes = json.loads(row["extract_table_notes"])
            result.append(
                {
                    "id": row["id"],
                    "document_id": row["document_id"],
                    "document_title": row["document_title"],
                    "dso_slug": row["dso_slug"],
                    "vnb_name": row["vnb_name"],
                    "tool": row["tool"],
                    "table_number": row["table_number"],
                    "first_page": _first_page(row["pages"]),
                    "page_count": len(json.loads(row["pages"])),
                    "title": notes.get("title") if isinstance(notes, dict) else None,
                    "is_selected": bool(row["is_selected"]),
                    "table_type": row["table_type"],
                    "is_confirmed": bool(row["extract_is_confirmed"]),
                    "has_review_file": row["extract_reviewed_table_path"] is not None,
                    "is_archived": bool(row["extract_is_archived"]),
                    "is_stale": bool(row["extract_reviewed_source_hash"])
                    and row["extract_reviewed_source_hash"] != row["extract_table_hash"],
                    "clean_count": row["clean_count"],
                    "created_at": row["extract_created_at"],
                }
            )
        return result

    @app.get("/api/overview/clean-tables")
    def clean_tables(
        extract_id: int | None = Query(default=None, gt=0),
        manual: bool = False,
        unresolved_modified: bool = False,
        unresolved: bool = False,
    ) -> list[dict[str, object]]:
        """Return cleaning versions, optionally filtered across all extractions.

        Args:
            extract_id: Optional source extraction ID.
            manual: Include versions with saved manual differences, including headers.
            unresolved_modified: Include failed automatic cells with reviewed changes.
            unresolved: Include automatic failures without reviewed changes.

        Returns:
            Cleaning table summaries.
        """
        with _read_database(repository) as connection:
            extract_exists = connection.execute(
                "SELECT 1 FROM extract_table WHERE id=?", (extract_id,)
            ).fetchone()
            if extract_id is not None and extract_exists is None:
                raise HTTPException(status_code=404, detail="Extracted table not found")
            rows = connection.execute(
                "SELECT c.id, c.extract_table_id, c.title, c.is_selected, c.clean_is_confirmed, "
                "c.clean_created_at, c.clean_updated_at, c.clean_table_notes, "
                "c.clean_table_hash, c.clear_reviewed_table_hash, c.clean_source_hash, "
                "c.clean_cells_path, c.clean_cells_hash, c.clear_reviewed_source_hash, "
                "e.extract_reviewed_table_hash, e.extract_table_hash, "
                "c.clean_table_path, c.clear_reviewed_table_path, e.document_id, e.tool, "
                "e.table_number, d.title AS document_title, v.slug AS dso_slug, v.name AS vnb_name "
                "FROM clean_table c JOIN extract_table e ON e.id=c.extract_table_id "
                "JOIN document d ON d.id=e.document_id JOIN dso v ON v.id=d.dso_id "
                "WHERE (? IS NULL OR c.extract_table_id=?) "
                "ORDER BY c.is_selected DESC, c.id DESC",
                (extract_id, extract_id),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            notes = json.loads(row["clean_table_notes"])
            legacy = isinstance(notes, dict) and notes.get("legacy_compared_id") is not None
            expected_source = row["extract_reviewed_table_hash"] or row["extract_table_hash"]
            unresolved_count = 0
            cells = []
            manual_cells: set[tuple[int, int]] = set()
            if row["clean_cells_path"]:
                cells_file = _verified_file(
                    repository, row["clean_cells_path"], row["clean_cells_hash"]
                )
                with cells_file.open(encoding="utf-8") as source:
                    cells = json.load(source)
                    unresolved_count = sum(cell.get("status") == "unresolved" for cell in cells)
            if row["clear_reviewed_table_path"]:
                automatic = _csv_rows(
                    _verified_file(repository, row["clean_table_path"], row["clean_table_hash"])
                )
                reviewed = _csv_rows(
                    _verified_file(
                        repository,
                        row["clear_reviewed_table_path"],
                        row["clear_reviewed_table_hash"],
                    )
                )
                manual_cells = {
                    (r, col)
                    for r, values in enumerate(reviewed)
                    for col, value in enumerate(values)
                    if value
                    != (automatic[r][col] if r < len(automatic) and col < len(automatic[r]) else "")
                }
            unresolved_modified_count = sum(
                cell.get("status") == "unresolved" and (cell["row"], cell["column"]) in manual_cells
                for cell in cells
            )
            pending_count = unresolved_count - unresolved_modified_count
            if (manual or unresolved_modified or unresolved) and not (
                (manual and manual_cells)
                or (unresolved_modified and unresolved_modified_count)
                or (unresolved and pending_count)
            ):
                continue
            result.append(
                {
                    "id": row["id"],
                    "title": row["title"] or f"Cleaning result #{row['id']}",
                    "extract_table_id": row["extract_table_id"],
                    "is_selected": bool(row["is_selected"]),
                    "is_confirmed": bool(row["clean_is_confirmed"]),
                    "is_legacy": legacy,
                    "is_stale": bool(row["clean_source_hash"])
                    and row["clean_source_hash"] != expected_source,
                    "has_review_file": row["clear_reviewed_table_hash"] is not None,
                    "review_is_stale": bool(row["clear_reviewed_table_hash"])
                    and row["clear_reviewed_source_hash"] != row["clean_table_hash"],
                    "unresolved_count": unresolved_count,
                    "manual_count": len(manual_cells),
                    "unresolved_modified_count": unresolved_modified_count,
                    "pending_count": pending_count,
                    "document_id": row["document_id"],
                    "document_title": row["document_title"],
                    "dso_slug": row["dso_slug"],
                    "vnb_name": row["vnb_name"],
                    "tool": row["tool"],
                    "table_number": row["table_number"],
                    "created_at": row["clean_created_at"],
                    "updated_at": row["clean_updated_at"],
                }
            )
        return result

    @app.get("/api/extract-review/{extract_id}")
    def extract_review(extract_id: int) -> dict[str, object]:
        """Return the editable review grid and source metadata.

        Args:
            extract_id: Extracted table ID.

        Returns:
            Review content, hashes, and PDF page numbers.
        """
        with _read_database(repository) as connection:
            row = _review_record(connection, extract_id)
        source_path = _verified_file(
            repository, row["extract_table_path"], row["extract_table_hash"]
        )
        with source_path.open("r", encoding="utf-8-sig", newline="") as source:
            source_rows = list(csv.reader(source))
        reviewed_rows: list[list[str]] | None = None
        if row["extract_reviewed_table_path"] is not None:
            reviewed_path = _verified_file(
                repository,
                row["extract_reviewed_table_path"],
                row["extract_reviewed_table_hash"],
            )
            with reviewed_path.open("r", encoding="utf-8-sig", newline="") as reviewed_source:
                reviewed_rows = list(csv.reader(reviewed_source))
        notes = json.loads(row["extract_reviewed_table_notes"])
        return {
            "id": row["id"],
            "tool": row["tool"],
            "table_number": row["table_number"],
            "document_title": row["document_title"],
            "pages": json.loads(row["pages"]),
            "regions": json.loads(row["regions"]),
            "rows": reviewed_rows if reviewed_rows is not None else source_rows,
            "source_rows": source_rows,
            "reviewed_rows": reviewed_rows,
            "source_hash": row["extract_table_hash"],
            "reviewed_hash": row["extract_reviewed_table_hash"],
            "is_confirmed": bool(row["extract_is_confirmed"]),
            "table_type": row["table_type"],
            "is_archived": bool(row["extract_is_archived"]),
            "note": notes.get("review_note", "") if isinstance(notes, dict) else "",
            "is_stale": bool(row["extract_reviewed_source_hash"])
            and row["extract_reviewed_source_hash"] != row["extract_table_hash"],
            "has_pdf": row["document_path"] is not None,
        }

    @app.get("/api/extract-review/{extract_id}/pdf")
    def extract_review_pdf(extract_id: int) -> FileResponse:
        """Stream the verified source PDF for the review viewer.

        Args:
            extract_id: Extracted table ID.

        Returns:
            Inline PDF response.
        """
        with _read_database(repository) as connection:
            row = _review_record(connection, extract_id)
        path = _verified_file(repository, row["document_path"], row["document_hash"])
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    @app.put("/api/extract-review/{extract_id}")
    def save_extract_review(extract_id: int, update: ExtractReviewUpdate) -> dict[str, object]:
        """Save an immutable reviewed CSV and update its metadata.

        Args:
            extract_id: Extracted table ID.
            update: Edited rows and expected source/review hashes.

        Returns:
            Updated review state.
        """
        if sum(len(row) for row in update.rows) > 200_000:
            raise HTTPException(status_code=413, detail="Table is too large to save on this page")
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\n").writerows(update.rows)
        content = output.getvalue().encode("utf-8")
        with connect(repository / "nap_tool.sqlite") as connection:
            row = _review_record(connection, extract_id)
            if (
                row["extract_table_hash"] != update.source_hash
                or row["extract_reviewed_table_hash"] != update.reviewed_hash
            ):
                raise HTTPException(
                    status_code=409, detail="Extraction or review changed; reload the page"
                )
            relative = f"extract_reviewed/{extract_id}/{hashlib.sha256(content).hexdigest()}.csv"
            digest = write_bytes(repository, relative, content)
            timestamp = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE extract_table SET extract_reviewed_table_hash=?, "
                "extract_reviewed_table_path=?, extract_reviewed_source_hash=?, "
                "extract_is_confirmed=?, "
                "extract_reviewed_table_created_at=COALESCE(extract_reviewed_table_created_at, ?), "
                "extract_reviewed_table_updated_at=? WHERE id=?",
                (
                    digest,
                    relative,
                    update.source_hash,
                    int(update.confirm),
                    timestamp,
                    timestamp,
                    extract_id,
                ),
            )
        return {"reviewed_hash": digest, "is_confirmed": update.confirm, "is_stale": False}

    @app.patch("/api/extract-review/{extract_id}/metadata")
    def update_extract_review_metadata(
        extract_id: int, update: ExtractReviewMetadataUpdate
    ) -> dict[str, object]:
        """Set the table type, archive state, or human review note.

        Args:
            extract_id: Extracted table ID.
            update: One metadata change and the expected file hashes.

        Returns:
            Current classification, archive state, and review note.
        """
        changes = (
            "table_type" in update.model_fields_set,
            update.is_archived is not None,
            update.note is not None,
        )
        if sum(changes) != 1:
            raise HTTPException(status_code=422, detail="Change one review field at a time")
        with connect(repository / "nap_tool.sqlite") as connection:
            row = _review_record(connection, extract_id)
            if (
                row["extract_table_hash"] != update.source_hash
                or row["extract_reviewed_table_hash"] != update.reviewed_hash
            ):
                raise HTTPException(
                    status_code=409, detail="Extraction or review changed; reload the page"
                )
            if "table_type" in update.model_fields_set:
                if (
                    update.table_type is not None
                    and connection.execute(
                        "SELECT 1 FROM table_type WHERE id=?", (update.table_type,)
                    ).fetchone()
                    is None
                ):
                    raise HTTPException(status_code=422, detail="Unknown table type")
                connection.execute(
                    "DELETE FROM extract_table_type WHERE extract_table_id=?", (extract_id,)
                )
                if update.table_type is not None:
                    connection.execute(
                        "INSERT INTO extract_table_type VALUES (?,?)",
                        (extract_id, update.table_type),
                    )
            elif update.is_archived is not None:
                connection.execute(
                    "UPDATE extract_table SET extract_is_archived=?, "
                    "is_selected=CASE WHEN ?=1 THEN 0 ELSE is_selected END WHERE id=?",
                    (int(update.is_archived), int(update.is_archived), extract_id),
                )
            else:
                notes = json.loads(row["extract_reviewed_table_notes"])
                if not isinstance(notes, dict):
                    notes = {}
                notes["review_note"] = update.note
                timestamp = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "UPDATE extract_table SET extract_reviewed_table_notes=?, "
                    "extract_reviewed_table_created_at="
                    "COALESCE(extract_reviewed_table_created_at, ?), "
                    "extract_reviewed_table_updated_at=? WHERE id=?",
                    (json.dumps(notes, ensure_ascii=False), timestamp, timestamp, extract_id),
                )
            updated = _review_record(connection, extract_id)
        updated_notes = json.loads(updated["extract_reviewed_table_notes"])
        return {
            "table_type": updated["table_type"],
            "is_archived": bool(updated["extract_is_archived"]),
            "note": updated_notes.get("review_note", "") if isinstance(updated_notes, dict) else "",
        }

    clean_router = APIRouter()
    install_clean_routes(clean_router, repository)
    app.include_router(clean_router)
    app.include_router(harmonize_router(repository))
    app.include_router(classify_router(repository))
    app.include_router(sets_router(repository))
    return app
