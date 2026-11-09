# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Metadata operations shared by discovery, download, and extraction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nap_tool.data import checked_file, write_bytes
from nap_tool.database.schema import connect
from nap_tool.document_metadata import infer_nap_year, version_dates


def now() -> str:
    """Return an ISO-8601 UTC timestamp.

    Returns:
        Current time in UTC.
    """
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Candidate:
    """A source document found before its PDF is downloaded.

    Attributes:
        provider_slug: Stable operator identifier.
        provider_name: Display name of the operator.
        source: Discovery source name.
        source_document_id: Stable source ID when available.
        title: Original document name.
        source_url: PDF URL.
        version: Source version or validity date.
    """

    provider_slug: str
    provider_name: str
    source: str
    source_document_id: str | None
    title: str
    source_url: str
    version: str | None = None


def store_candidates(database: Path, candidates: list[Candidate]) -> tuple[int, int]:
    """Upsert providers and pending source documents.

    Args:
        database: Metadata database.
        candidates: Discovered source documents.

    Returns:
        Number of new and already known documents.
    """
    created = 0
    known = 0
    with connect(database) as connection:
        for candidate in candidates:
            stamp = now()
            connection.execute(
                "INSERT INTO dso(name, slug, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(slug) DO UPDATE SET name=excluded.name, "
                "updated_at=excluded.updated_at",
                (candidate.provider_name, candidate.provider_slug, stamp, stamp),
            )
            dso_id = connection.execute(
                "SELECT id FROM dso WHERE slug=?", (candidate.provider_slug,)
            ).fetchone()[0]
            existing = connection.execute(
                "SELECT id, hash, version FROM document WHERE dso_id=? AND source=? "
                "AND COALESCE(source_document_id, '')=COALESCE(?, '') AND source_url=? "
                "ORDER BY id DESC LIMIT 1",
                (dso_id, candidate.source, candidate.source_document_id, candidate.source_url),
            ).fetchone()
            if existing is not None:
                if existing["hash"] is None:
                    version, current_to = version_dates(candidate.version)
                    connection.execute(
                        "UPDATE document SET title=?, version=?, current_to=?, "
                        "updated_at=? WHERE id=?",
                        (candidate.title, version, current_to, stamp, existing["id"]),
                    )
                known += 1
                continue
            version, current_to = version_dates(candidate.version)
            connection.execute(
                "INSERT INTO document(dso_id, title, source_document_id, source_url, source, "
                "version, current_to, nap_year, is_selected, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    dso_id,
                    candidate.title,
                    candidate.source_document_id,
                    candidate.source_url,
                    candidate.source,
                    version,
                    current_to,
                    infer_nap_year(candidate.title, candidate.version),
                    stamp,
                    stamp,
                ),
            )
            created += 1
    return created, known


def documents_for_download(
    database: Path, provider: str | None, document: str | None, force: bool
) -> list[sqlite3.Row]:
    """Select pending documents, or downloaded documents for a forced refresh.

    Args:
        database: Metadata database.
        provider: Optional provider slug.
        document: Optional exact title or numeric document ID.
        force: Include previously downloaded documents.

    Returns:
        Matching document rows.
    """
    query = "SELECT d.*, v.slug FROM document d JOIN dso v ON v.id=d.dso_id WHERE 1=1"
    parameters: list[str | int] = []
    if not force:
        query += " AND d.file_path IS NULL"
    elif document is None:
        query += " AND d.is_selected=1 AND d.source_url IS NOT NULL"
    if provider is not None:
        query += " AND v.slug=?"
        parameters.append(provider)
    if document is not None:
        query += " AND (d.title=? OR d.id=?)" if document.isdecimal() else " AND d.title=?"
        parameters.append(document)
        if document.isdecimal():
            parameters.append(int(document))
    query += " ORDER BY v.slug, d.id"
    with connect(database) as connection:
        return connection.execute(query, parameters).fetchall()


def create_download_run(database: Path, script: str) -> int:
    """Create one run for one CLI download invocation.

    Args:
        database: Metadata database.
        script: Invoked command line.

    Returns:
        New run ID.
    """
    with connect(database) as connection:
        return connection.execute(
            "INSERT INTO download_run(script, created_at) VALUES (?, ?) RETURNING id",
            (script, now()),
        ).fetchone()[0]


def record_download(
    database: Path, root: Path, row: sqlite3.Row, content: bytes, run_id: int
) -> tuple[int, bool]:
    """Persist a verified PDF and its first download run.

    Args:
        database: Metadata database.
        root: Data repository root.
        row: Discovered document.
        content: PDF bytes.
        run_id: Download invocation ID.

    Returns:
        Document ID and whether this content was newly stored.

    Raises:
        ValueError: If content is not a PDF.
    """
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Source did not return a PDF: document #{row['id']}")
    digest = hashlib.sha256(content).hexdigest()
    relative = f"pdf/{row['slug']}/{digest[:16]}.pdf"
    write_bytes(root, relative, content)
    with connect(database) as connection:
        existing = connection.execute(
            "SELECT id FROM document WHERE dso_id=? AND hash=?",
            (row["dso_id"], digest),
        ).fetchone()
        if existing is not None and existing["id"] != row["id"]:
            if row["hash"] is None:
                connection.execute("DELETE FROM document WHERE id=?", (row["id"],))
            return existing["id"], False
        if row["hash"] == digest:
            return row["id"], False
        stamp = now()
        if row["hash"] is None:
            document_id = row["id"]
            connection.execute(
                "UPDATE document SET created_by_run_id=?, hash=?, file_path=?, "
                "is_selected=1, updated_at=? WHERE id=?",
                (run_id, digest, relative, stamp, document_id),
            )
            if row["source"] == "vnbdigital":
                # One current NAP per operator and NAP year: a new report replaces the
                # previous one of the same year, never the plans of other years.
                connection.execute(
                    "UPDATE document SET is_selected=0 WHERE dso_id=? AND source=? "
                    "AND nap_year IS ? AND id<>?",
                    (row["dso_id"], row["source"], row["nap_year"], document_id),
                )
            elif row["source_document_id"] is not None:
                connection.execute(
                    "UPDATE document SET is_selected=0 WHERE dso_id=? AND source=? "
                    "AND source_document_id=? AND id<>?",
                    (row["dso_id"], row["source"], row["source_document_id"], document_id),
                )
        else:
            document_id = connection.execute(
                "INSERT INTO document(dso_id, created_by_run_id, title, source_document_id, "
                "hash, source_url, source, version, current_to, nap_year, "
                "file_path, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (
                    row["dso_id"],
                    run_id,
                    row["title"],
                    row["source_document_id"],
                    digest,
                    row["source_url"],
                    row["source"],
                    row["version"],
                    row["current_to"],
                    row["nap_year"],
                    relative,
                    stamp,
                    stamp,
                ),
            ).fetchone()[0]
            connection.execute("UPDATE document SET is_selected=0 WHERE id=?", (row["id"],))
        return document_id, True


def documents_for_extraction(
    database: Path, provider: str | None, document: str | None, tool: str, force: bool
) -> list[sqlite3.Row]:
    """Select downloaded documents needing extraction with a tool.

    Args:
        database: Metadata database.
        provider: Optional provider slug.
        document: Optional exact title or numeric ID.
        tool: Extractor name.
        force: Include already extracted documents.

    Returns:
        Matching document rows.
    """
    query = (
        "SELECT d.*, v.slug FROM document d JOIN dso v ON v.id=d.dso_id "
        "WHERE d.file_path LIKE '%.pdf'"
    )
    parameters: list[str | int] = []
    if document is None:
        query += " AND d.is_selected=1"
    if not force:
        query += " AND NOT EXISTS (SELECT 1 FROM extract_table e "
        query += "WHERE e.document_id=d.id AND e.tool=? AND e.extract_is_archived=0)"
        parameters.append(tool)
    if provider is not None:
        query += " AND v.slug=?"
        parameters.append(provider)
    if document is not None:
        query += " AND (d.title=? OR d.id=?)" if document.isdecimal() else " AND d.title=?"
        parameters.append(document)
        if document.isdecimal():
            parameters.append(int(document))
    query += " ORDER BY v.slug, d.id"
    with connect(database) as connection:
        return connection.execute(query, parameters).fetchall()


def verify_document(root: Path, row: sqlite3.Row) -> Path:
    """Verify a document's PDF before extraction.

    Args:
        root: Data repository root.
        row: Downloaded document row.

    Returns:
        Verified PDF path.
    """
    return checked_file(root, row["file_path"], row["hash"])


def store_extraction(
    database: Path,
    root: Path,
    document_id: int,
    tool: str,
    output: Path,
    script_path: str,
    script_hash: str,
) -> int:
    """Import one extractor result without replacing prior reviewed data.

    Args:
        database: Metadata database.
        root: Data repository root.
        document_id: Source document ID.
        tool: Extractor name.
        output: Directory with metadata.json and CSV files.
        script_path: Saved extraction code snapshot.
        script_hash: Snapshot SHA-256.

    Returns:
        Number of extracted tables stored.
    """
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    tables = metadata["tables"]
    if not tables:
        return 0
    source = f"{document_id}/{tool}/{script_hash[:12]}/{metadata['generated_at']}"
    source_key = hashlib.sha256(source.encode()).hexdigest()[:12]
    base = (
        f"extracted/{metadata['provider_slug']}/"
        f"{metadata['source_sha256'][:16]}/{tool}/{source_key}"
    )
    native_files: list[dict[str, str]] = []
    native = output / "result" / "nap"
    if native.is_dir():
        for path in sorted(native.rglob("*")):
            if path.is_file():
                relative = f"{base}/native/{path.relative_to(native).as_posix()}"
                digest = write_bytes(root, relative, path.read_bytes())
                native_files.append({"path": relative, "hash": digest})
    with connect(database) as connection:
        connection.execute(
            "UPDATE extract_table SET extract_is_archived=1, is_selected=0 "
            "WHERE document_id=? AND tool=? AND extract_is_archived=0",
            (document_id, tool),
        )
        for table in tables:
            content = (output / table["file"]).read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            relative = f"{base}/table_{table['table_number']:03}.csv"
            write_bytes(root, relative, content)
            notes = {
                key: table.get(key)
                for key in ("rows", "columns", "title", "source_id", "status", "merged")
            }
            if native_files:
                notes["native_files"] = native_files
            connection.execute(
                "INSERT INTO extract_table(document_id, tool, table_number, "
                "page_table_index, pages, regions, extract_table_hash, extract_table_path, "
                "extract_table_notes, extract_script, extract_script_hash, extract_created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    tool,
                    table["table_number"],
                    table["table_number"],
                    json.dumps(table.get("pages", [])),
                    json.dumps(table.get("regions", [])),
                    digest,
                    relative,
                    json.dumps(notes),
                    script_path,
                    script_hash,
                    now(),
                ),
            )
    return len(tables)
