# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""The metadata schema and SQLite connection lifecycle."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Format version of the nap_data repository, stored in nap_tool.sqlite as
# PRAGMA user_version. Bump it when a nap_tool built for the old value would fail
# on or misread data written under the new value, or the reverse: SQL schema,
# seeded ids such as TABLE_TYPE_GRID_MEASURES, stored path layout, or file
# formats the code parses. New documents, tables, reviews and outputs never bump
# it. connect() never upgrades a database; `nap-tool upgrade` (database/upgrade.py)
# applies a step's changes and then sets the new user_version.
DB_VERSION = 22
TABLE_TYPE_GRID_MEASURES = 1
TABLE_TYPE_REGIONAL_SCENARIO_PARAMETERS = 2
TYPE_SCHEMA = """
CREATE TABLE IF NOT EXISTS table_type (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
INSERT OR IGNORE INTO table_type(id,name) VALUES
    (1, 'Maßnahmentabelle'), (2, 'Regionale Szenarioparameter');
"""
CLASSIFICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS extract_table_type (
    extract_table_id INTEGER PRIMARY KEY REFERENCES extract_table(id) ON DELETE CASCADE,
    table_type_id INTEGER NOT NULL REFERENCES table_type(id)
);
CREATE INDEX IF NOT EXISTS extract_type ON extract_table_type(table_type_id);
"""
SET_SCHEMA = """
CREATE TABLE IF NOT EXISTS harmonize_set (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
    table_type_id INTEGER NOT NULL REFERENCES table_type(id),
    dso_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(dso_ids)),
    years TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(years)),
    current_scheme_id INTEGER REFERENCES harmonize_scheme(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);
"""
SET_OUTPUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS harmonize_set_output (
    set_id INTEGER NOT NULL REFERENCES harmonize_set(id) ON DELETE CASCADE,
    scheme_id INTEGER NOT NULL REFERENCES harmonize_scheme(id) ON DELETE CASCADE,
    output_path TEXT NOT NULL, output_hash TEXT NOT NULL,
    source_manifest_hash TEXT, generated_at TEXT NOT NULL,
    PRIMARY KEY (set_id, scheme_id)
);
CREATE INDEX IF NOT EXISTS harmonize_output_scheme ON harmonize_set_output(scheme_id);
"""
HARMONIZE_SCHEMA = """
CREATE TABLE IF NOT EXISTS harmonize_scheme (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
    slug TEXT UNIQUE,
    initial_set_id INTEGER REFERENCES harmonize_set(id) ON DELETE SET NULL,
    copy_from_scheme_id INTEGER REFERENCES harmonize_scheme(id),
    table_settings TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(table_settings)),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""
# Location proposals for records, independent of any set (ADR-0008); history is never deleted.
PROPOSAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposal (
    id INTEGER PRIMARY KEY, row_id TEXT NOT NULL, input_sha256 TEXT NOT NULL,
    -- skill_version stays NULL for a human correction (model = 'human').
    model TEXT NOT NULL, skill_version TEXT, created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'accepted', 'rejected')),
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS proposal_row ON proposal(row_id, input_sha256);
CREATE TABLE IF NOT EXISTS proposal_location (
    id INTEGER PRIMARY KEY, proposal_id INTEGER NOT NULL REFERENCES proposal(id),
    role TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
    evidence_field TEXT NOT NULL, evidence_quote TEXT NOT NULL, candidate TEXT
);
CREATE INDEX IF NOT EXISTS proposal_location_proposal ON proposal_location(proposal_id);
"""
SCHEMA = (
    TYPE_SCHEMA
    + """
CREATE TABLE IF NOT EXISTS download_run (
    id INTEGER PRIMARY KEY, script TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dso (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
    info TEXT NOT NULL DEFAULT '{}', mastr_nr TEXT, bdew_code TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY, dso_id INTEGER NOT NULL REFERENCES dso(id),
    created_by_run_id INTEGER REFERENCES download_run(id),
    title TEXT NOT NULL, source_document_id TEXT, hash TEXT, source_url TEXT,
    source TEXT NOT NULL, version TEXT, current_to TEXT, file_path TEXT,
    nap_year INTEGER CHECK (nap_year BETWEEN 2000 AND 2100),
    is_selected INTEGER NOT NULL DEFAULT 1 CHECK (is_selected IN (0, 1)),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK ((hash IS NULL) = (file_path IS NULL)),
    UNIQUE (dso_id, hash)
);
CREATE INDEX IF NOT EXISTS document_source ON document(dso_id, source, source_document_id);
CREATE TABLE IF NOT EXISTS extract_table (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES document(id),
    tool TEXT NOT NULL, table_number INTEGER NOT NULL,
    is_selected INTEGER NOT NULL DEFAULT 1,
    page_table_index INTEGER, pages TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(pages)),
    regions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(regions)),
    extract_table_hash TEXT NOT NULL, extract_table_path TEXT NOT NULL,
    extract_table_notes TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extract_table_notes)),
    extract_script TEXT, extract_script_hash TEXT,
    extract_created_at TEXT NOT NULL,
    extract_reviewed_table_hash TEXT, extract_reviewed_table_path TEXT,
    extract_reviewed_table_notes TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(extract_reviewed_table_notes)),
    extract_is_confirmed INTEGER NOT NULL DEFAULT 0,
    extract_is_archived INTEGER NOT NULL DEFAULT 0,
    extract_reviewed_table_created_at TEXT,
    extract_reviewed_table_updated_at TEXT,
    extract_reviewed_source_hash TEXT,
    CHECK ((extract_reviewed_table_hash IS NULL) = (extract_reviewed_table_path IS NULL))
);
CREATE INDEX IF NOT EXISTS extract_document ON extract_table(document_id, tool);
CREATE TABLE IF NOT EXISTS clean_table (
    id INTEGER PRIMARY KEY, extract_table_id INTEGER NOT NULL REFERENCES extract_table(id),
    title TEXT NOT NULL DEFAULT '',
    clean_table_hash TEXT NOT NULL, clean_table_path TEXT NOT NULL,
    clean_table_notes TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(clean_table_notes)),
    clean_config TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(clean_config)),
    clean_cells_hash TEXT, clean_cells_path TEXT,
    clean_script TEXT, clean_script_hash TEXT, clean_source_hash TEXT,
    clear_reviewed_table_hash TEXT, clear_reviewed_table_path TEXT,
    clear_reviewed_source_hash TEXT,
    clear_reviewed_table_notice TEXT,
    clean_is_confirmed INTEGER NOT NULL DEFAULT 0,
    clean_created_at TEXT NOT NULL, clean_updated_at TEXT NOT NULL,
    is_selected INTEGER NOT NULL DEFAULT 1,
    CHECK ((clear_reviewed_table_hash IS NULL) = (clear_reviewed_table_path IS NULL)),
    CHECK ((clean_cells_hash IS NULL) = (clean_cells_path IS NULL))
);
CREATE INDEX IF NOT EXISTS clean_extract ON clean_table(extract_table_id);
CREATE TABLE IF NOT EXISTS harmonize_field (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL,
    scheme_id INTEGER REFERENCES harmonize_scheme(id) ON DELETE CASCADE,
    field_key TEXT, position INTEGER,
    scope TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS harmonize_field_source (
    id INTEGER PRIMARY KEY,
    field_id INTEGER NOT NULL REFERENCES harmonize_field(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    extract_id INTEGER NOT NULL REFERENCES extract_table(id),
    column_index INTEGER NOT NULL CHECK (column_index >= 0),
    header TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto', 'fixed')),
    stage TEXT,
    clean_id INTEGER REFERENCES clean_table(id),
    source_hash TEXT,
    UNIQUE (field_id, position)
);
CREATE INDEX IF NOT EXISTS harmonize_source_extract ON harmonize_field_source(extract_id);
CREATE INDEX IF NOT EXISTS harmonize_source_clean ON harmonize_field_source(clean_id);
"""
    + CLASSIFICATION_SCHEMA
    + HARMONIZE_SCHEMA
    + SET_SCHEMA
    + SET_OUTPUT_SCHEMA
    + PROPOSAL_SCHEMA
    + f"PRAGMA user_version = {DB_VERSION};"
)


class DatabaseVersionError(RuntimeError):
    """The metadata database format differs from this nap_tool's DB_VERSION."""


def _has_document_table(connection: sqlite3.Connection) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document'"
        ).fetchone()
        is not None
    )


def require_version(connection: sqlite3.Connection, path: Path) -> None:
    """Refuse a metadata database whose format differs from this nap_tool.

    Args:
        connection: Open metadata database.
        path: Database path, named in the error message.

    Raises:
        DatabaseVersionError: If the database version differs from DB_VERSION;
            the message says which repository to update, or how to create or
            import the database.
    """
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == DB_VERSION:
        return
    if version == 0 and _has_document_table(connection):
        raise DatabaseVersionError(
            f"{path} is an old, unversioned database; move it out of NAP_DATA_DIR "
            "and import it with `nap-tool migrate --from-db <old.sqlite>`"
        )
    if version == 0:
        raise DatabaseVersionError(f"{path} has no schema; run `nap-tool discover` to create it")
    if version > DB_VERSION:
        raise DatabaseVersionError(
            f"{path} has DB_VERSION {version}, newer than this nap_tool "
            f"({DB_VERSION}); update nap_tool (git pull)"
        )
    raise DatabaseVersionError(
        f"{path} has DB_VERSION {version}, older than this nap_tool ({DB_VERSION}); "
        f"update nap_data (git -C {path.parent} pull); if it is still older, "
        "run `nap-tool upgrade`"
    )


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a metadata database and commit or roll back a transaction.

    Args:
        path: SQLite database path.

    Yields:
        Connection with row access by column name.

    Raises:
        DatabaseVersionError: If the database version differs from DB_VERSION.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 and not _has_document_table(connection):
            connection.executescript(SCHEMA)
        else:
            require_version(connection, path)
        yield connection
        connection.commit()
    finally:
        connection.close()
