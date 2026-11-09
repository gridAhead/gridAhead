# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Migrate source documents and extraction reviews from the old BLOB repository."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import typer

from nap_tool.data import data_dir, write_bytes
from nap_tool.database.repository import now
from nap_tool.database.schema import connect


def migrate(
    from_db: Path = typer.Option(..., "--from-db", help="Old nap_tool.sqlite database"),
) -> None:
    """Copy all old data into the new file-based repository.

    Args:
        from_db: Old BLOB database to migrate.
    """
    try:
        root = data_dir()
        counts = migrate_database(from_db, root)
    except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
        typer.echo(f"Migration failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Migration complete: {json.dumps(counts, sort_keys=True)}")


def migrate_database(source_path: Path, root: Path) -> dict[str, int]:
    """Migrate old documents and extractions, omitting obsolete comparison outputs.

    Args:
        source_path: Existing legacy SQLite database.
        root: New data repository directory.

    Returns:
        Migrated row counts by stage.

    Raises:
        RuntimeError: If the target already has a database or the source is invalid.
    """
    destination = root / "nap_tool.sqlite"
    if destination.exists():
        raise RuntimeError(f"Target database already exists: {destination}")
    if not source_path.is_file():
        raise RuntimeError(f"Source database not found: {source_path}")
    temporary = root / ".nap_tool.migrating.sqlite"
    if temporary.exists():
        temporary.unlink()
    counts: dict[str, int] = {}
    source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        with connect(temporary) as target:
            _migrate_runs(source, target)
            _migrate_vnbs(source, target)
            counts["document"] = _migrate_documents(source, target, root)
            counts["extract_table"] = _migrate_extracted(source, target, root)
            counts["table_review"] = _migrate_reviews(source, target, root)
            counts["clean_table"] = 0
            counts["measures_table"] = _migrate_measures(source, target)
            counts["review_source"] = _migrate_review_sources(source, target, root)
            _verify_counts(source, target, counts)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
        source.close()
    return counts


def _migrate_runs(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    for row in source.execute("SELECT * FROM run"):
        target.execute(
            "INSERT INTO download_run(id, script, created_at) VALUES (?, ?, ?)",
            (row["run_id"], "legacy import: command unavailable", row["run_datetime"]),
        )


def _migrate_vnbs(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    stamp = now()
    for row in source.execute("SELECT * FROM vnb"):
        target.execute(
            "INSERT INTO dso(id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (row["provider_id"], row["provider_name"], row["provider_slug"], stamp, stamp),
        )


def _source_id(url: str | None) -> str | None:
    if url is None:
        return None
    return parse_qs(urlparse(url).query).get("fileId", [None])[0]


def _migrate_documents(source: sqlite3.Connection, target: sqlite3.Connection, root: Path) -> int:
    providers = {
        row["provider_id"]: row["provider_slug"] for row in source.execute("SELECT * FROM vnb")
    }
    runs = {
        row["document_id"]: row["run_id"] for row in source.execute("SELECT * FROM run_document")
    }
    count = 0
    for row in source.execute("SELECT * FROM document ORDER BY document_id"):
        content = row["file"]
        digest = row["sha256"]
        relative = None
        if content is not None:
            actual = hashlib.sha256(content).hexdigest()
            if actual != digest:
                raise ValueError(f"PDF hash mismatch in old document #{row['document_id']}")
            relative = f"pdf/{providers[row['vnb_id']]}/{digest[:16]}.pdf"
            write_bytes(root, relative, content)
        version = row["current_from"]
        target.execute(
            "INSERT INTO document(id, dso_id, created_by_run_id, title, source_document_id, "
            "hash, source_url, source, version, current_to, nap_year, "
            "file_path, is_selected, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["document_id"],
                row["vnb_id"],
                runs.get(row["document_id"]),
                row["document_name"],
                _source_id(row["source_url"]),
                digest,
                row["source_url"],
                row["source"],
                version,
                row["current_to"],
                row["nap_year"],
                relative,
                int(content is not None),
                now(),
                now(),
            ),
        )
        count += 1
    return count


def _migrate_extracted(source: sqlite3.Connection, target: sqlite3.Connection, root: Path) -> int:
    tools = {row["extractor_id"]: row["name"] for row in source.execute("SELECT * FROM extractor")}
    documents = {
        row["id"]: (row["hash"], row["slug"])
        for row in target.execute(
            "SELECT d.id, d.hash, v.slug FROM document d JOIN dso v ON v.id=d.dso_id"
        )
    }
    count = 0
    for row in source.execute("SELECT * FROM table_extracted ORDER BY table_extracted_id"):
        digest = hashlib.sha256(row["data"]).hexdigest()
        document_hash, slug = documents[row["document_id"]]
        relative = (
            f"extracted/{slug}/{document_hash[:16]}/{tools[row['extractor_id']]}"
            f"/legacy/table_{row['table_extracted_id']:05}.csv"
        )
        write_bytes(root, relative, row["data"])
        notes = {
            "legacy_id": row["table_extracted_id"],
            "rows": row["rows"],
            "columns": row["columns"],
            "title": row["title"],
            "source_id": row["source_id"],
            "status": row["status"],
            "imported_from": row["imported_from"],
            "source_markdown": row["source_markdown"],
        }
        target.execute(
            "INSERT INTO extract_table(id, document_id, tool, table_number, "
            "page_table_index, pages, regions, extract_table_hash, extract_table_path, "
            "extract_table_notes, extract_created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["table_extracted_id"],
                row["document_id"],
                tools[row["extractor_id"]],
                row["table_number"],
                row["table_number"],
                row["pages_json"],
                row["regions_json"],
                digest,
                relative,
                json.dumps(notes, ensure_ascii=False),
                now(),
            ),
        )
        count += 1
    return count


def _review_csv(rows: list[list[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _migrate_reviews(source: sqlite3.Connection, target: sqlite3.Connection, root: Path) -> int:
    count = 0
    for row in source.execute("SELECT * FROM table_review ORDER BY review_id"):
        extracted = target.execute(
            "SELECT extract_table_path, extract_table_hash FROM extract_table WHERE id=?",
            (row["table_extracted_id"],),
        ).fetchone()
        draft = json.loads(row["draft_json"])
        notes = {
            "legacy_review_id": row["review_id"],
            "mark": row["mark"],
            "note": row["note"],
            "draft": draft,
            "history": json.loads(row["history_json"]),
            "legacy_source_hash": row["source_data_sha256"],
        }
        digest = None
        relative = None
        if row["mark"] == "approved" and draft.get("rows"):
            content = _review_csv(draft["rows"])
            relative = extracted["extract_table_path"].replace("extracted/", "extract_reviewed/", 1)
            digest = write_bytes(root, relative, content)
        target.execute(
            "UPDATE extract_table SET extract_reviewed_table_hash=?, "
            "extract_reviewed_table_path=?, extract_reviewed_table_notes=?, "
            "extract_is_confirmed=?, extract_reviewed_table_created_at=?, "
            "extract_reviewed_table_updated_at=?, extract_reviewed_source_hash=? WHERE id=?",
            (
                digest,
                relative,
                json.dumps(notes, ensure_ascii=False),
                int(row["mark"] == "approved"),
                row["updated_at"],
                row["updated_at"],
                row["source_data_sha256"],
                row["table_extracted_id"],
            ),
        )
        count += 1
    return count


def _migrate_measures(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    count = 0
    for row in source.execute("SELECT * FROM table_harmonized"):
        links = source.execute(
            "SELECT table_extracted_id FROM comparison WHERE table_compared_id=?",
            (row["table_compared_id"],),
        ).fetchall()
        if len(links) != 1:
            raise ValueError("Old measure table has an ambiguous extracted source")
        target.execute("INSERT OR REPLACE INTO extract_table_type VALUES (?,1)", (links[0][0],))
        count += 1
    return count


def _migrate_review_sources(
    source: sqlite3.Connection, target: sqlite3.Connection, root: Path
) -> int:
    count = 0
    for row in source.execute("SELECT * FROM extraction_review_source"):
        content = json.dumps(
            {
                "document_id": row["document_id"],
                "extractor_id": row["extractor_id"],
                "map": json.loads(row["map_json"]),
                "output_markdown": row["output_markdown"],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        relative = (
            f"legacy/review_source/document_{row['document_id']}_tool_{row['extractor_id']}.json"
        )
        write_bytes(root, relative, content)
        # The archived JSON is self-describing; it needs no SQL index.
        count += 1
    return count


def _verify_counts(
    source: sqlite3.Connection, target: sqlite3.Connection, counts: dict[str, int]
) -> None:
    expected = {
        "document": "document",
        "extract_table": "table_extracted",
        "table_review": "table_review",
        "measures_table": "table_harmonized",
        "review_source": "extraction_review_source",
    }
    for key, old_table in expected.items():
        old_count = source.execute(f"SELECT COUNT(*) FROM {old_table}").fetchone()[0]
        if counts[key] != old_count:
            raise ValueError(f"Migration count mismatch for {key}: {counts[key]} != {old_count}")
    for key in ("document", "extract_table", "clean_table"):
        new_count = target.execute(f"SELECT COUNT(*) FROM {key}").fetchone()[0]
        if counts[key] != new_count:
            raise ValueError(f"Target count mismatch for {key}")
