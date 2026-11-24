# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only metadata access and atomic classified-output publication."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from nap_tool.data import checked_file, resolve_path
from nap_tool.database.schema import TABLE_TYPE_GRID_MEASURES, require_version
from nap_tool.generations import (
    csv_bytes,
    json_bytes,
    publish_generation,
    published_directory,
    scheme_lock,
)

from . import ClassificationResult, classify
from .config import CONFIG_PATH, load_config
from .rules import DERIVED_FIELDS
from .validation import markdown_report, with_metric_expectations

GRID_MEASURE_TYPE_PREFIX = "Maßnahmentabelle"
OUTPUT_FILES = (
    "classified.csv",
    "validation_report.md",
    "validation_report.json",
    "unmapped_values.csv",
)


def is_grid_measure_type(connection: sqlite3.Connection, table_type_id: int) -> bool:
    """Tell whether a table type is a grid-measure table, such as one per NAP year.

    Args:
        connection: Open metadata database.
        table_type_id: Table type to check.

    Returns:
        True for the built-in grid-measure type and for types named like it,
        for example "Maßnahmentabelle 2026".
    """
    if table_type_id == TABLE_TYPE_GRID_MEASURES:
        return True
    row = connection.execute("SELECT name FROM table_type WHERE id=?", (table_type_id,)).fetchone()
    return row is not None and row["name"].casefold().startswith(
        GRID_MEASURE_TYPE_PREFIX.casefold()
    )


def year_config_path(config_path: Path, years: list[int]) -> Path:
    """Pick the year-specific classification YAML for a set of a single NAP year.

    Args:
        config_path: Requested classification YAML.
        years: NAP years selected by the set; empty means all years.

    Returns:
        ``classify_<year>.yaml`` beside the default file when the default file was
        requested, the set has exactly one year and that file exists; otherwise the
        requested path. An explicitly chosen non-default file is never replaced.
    """
    if config_path != CONFIG_PATH or len(years) != 1:
        return config_path
    candidate = config_path.with_name(f"classify_{years[0]}.yaml")
    return candidate if candidate.is_file() else config_path


@contextmanager
def database(root: Path) -> Iterator[sqlite3.Connection]:
    """Open the metadata database read-only after checking its version.

    Args:
        root: Data repository root.

    Yields:
        Read-only connection with row access by column name.

    Raises:
        ValueError: If the database file is missing.
        RuntimeError: If the database version differs from DB_VERSION.
    """
    path = root / "nap_tool.sqlite"
    if not path.is_file():
        raise ValueError(f"Metadata database not found: {path}; check NAP_DATA_DIR")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        require_version(connection, path)
        yield connection
    finally:
        connection.close()


def selected_set(root: Path, scheme_id: int, set_id: int | None) -> int:
    with database(root.resolve()) as connection:
        scheme = connection.execute(
            "SELECT initial_set_id FROM harmonize_scheme WHERE id=?", (scheme_id,)
        ).fetchone()
        if scheme is None:
            raise ValueError("Harmonization scheme not found")
        effective_set = set_id if set_id is not None else scheme["initial_set_id"]
        if effective_set is None:
            raise ValueError("Choose a set before running classification")
        selected = connection.execute(
            "SELECT table_type_id FROM harmonize_set WHERE id=?", (effective_set,)
        ).fetchone()
        if selected is None or not is_grid_measure_type(connection, selected["table_type_id"]):
            raise ValueError("Classification requires an existing grid-measure set")
        return effective_set


def inputs(
    root: Path,
    scheme_id: int | None = None,
    config_path: Path = CONFIG_PATH,
    *,
    set_id: int | None = None,
) -> dict:
    root = root.resolve()
    with database(root) as connection:
        if scheme_id is None:
            raise ValueError("Choose a harmonization scheme before running classification")
        scheme = connection.execute(
            "SELECT * FROM harmonize_scheme WHERE id=?", (scheme_id,)
        ).fetchone()
        if scheme is None:
            raise ValueError("Harmonization scheme not found")
        if set_id is None:
            set_id = scheme["initial_set_id"]
        if set_id is None:
            raise ValueError("Choose a set before running classification")
        selected = connection.execute(
            "SELECT * FROM harmonize_set WHERE id=?", (set_id,)
        ).fetchone()
        if selected is None or not is_grid_measure_type(connection, selected["table_type_id"]):
            raise ValueError("Classification requires an existing grid-measure set")
        config_path = year_config_path(config_path, json.loads(selected["years"]))
        pair = connection.execute(
            "SELECT * FROM harmonize_set_output WHERE set_id=? AND scheme_id=?",
            (set_id, scheme["id"]),
        ).fetchone()
        if pair is None:
            raise ValueError("Selected set has no output; generate its harmonized table first")
        scheme = {**dict(scheme), **dict(pair), "id": scheme["id"]}
        if not scheme["source_manifest_hash"]:
            raise ValueError("Harmonized output is stale; regenerate it first")
        path = checked_file(root, scheme["output_path"], scheme["output_hash"])
        fields = [
            dict(row)
            for row in connection.execute(
                "SELECT field_key,title FROM harmonize_field "
                "WHERE scheme_id=? ORDER BY position,id",
                (scheme["id"],),
            )
        ]
        identifiers = {
            row["slug"]: {key: row[key] or "" for key in ["name", "mastr_nr", "bdew_code"]}
            for row in connection.execute("SELECT * FROM dso ORDER BY slug")
        }
        # Source/cleaning changes can invalidate a generated table without altering its CSV.
        # Use the same source resolver as harmonization; never modify metadata here.
        from fastapi import HTTPException

        from nap_tool.ui.harmonize_api import (
            _fields,
            _pair_manifest,
            _pair_tables,
        )

        try:
            tables = _pair_tables(connection, root, scheme, pair["set_id"])
        except HTTPException as error:
            raise ValueError(f"Harmonized source unavailable: {error.detail}") from error
        current = _pair_manifest(_fields(connection, scheme, tables), tables)
        if current != scheme["source_manifest_hash"]:
            raise ValueError("Harmonized sources changed; regenerate the harmonized table first")
    config = load_config(config_path)
    fingerprint = hashlib.sha256(
        json_bytes(
            {
                "input_hash": scheme["output_hash"],
                "set_id": set_id,
                "fields": fields,
                "scheme_updated_at": scheme["updated_at"],
                "identifiers": identifiers,
                "config": config.model_dump(),
            }
        )
    ).hexdigest()
    return dict(
        scheme=dict(scheme),
        set_id=set_id,
        path=path,
        fields=fields,
        identifiers=identifiers,
        config=config,
        fingerprint=fingerprint,
    )


def load_rows(state: dict) -> tuple[list[dict[str, str]], list[str], dict[str, str]]:
    with state["path"].open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("Ambiguous duplicate CSV headers; fix the harmonization scheme")
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("Malformed CSV row; regenerate the harmonized table")
    mapping = {header: header for header in headers}
    for field in state["fields"]:
        key, title = field["field_key"], field["title"]
        if key and title in headers:
            if key in mapping and mapping[key] != title:
                raise ValueError(f"Ambiguous field mapping: {key}; fix the harmonization scheme")
            mapping[key] = title
    missing = [key for key in state["config"].required_fields if key not in mapping]
    if missing:
        raise ValueError(
            "Missing required input fields: "
            + ", ".join(missing)
            + "; fix and regenerate the harmonization scheme"
        )
    if set(headers) & set(DERIVED_FIELDS):
        raise ValueError("Input contains reserved derived fields; fix the harmonization scheme")
    return rows, headers, mapping


def run(
    root: Path,
    scheme_id: int | None = None,
    config_path: Path = CONFIG_PATH,
    *,
    set_id: int | None = None,
) -> ClassificationResult:
    root = root.resolve()
    state = inputs(root, scheme_id, config_path, set_id=set_id)
    scheme_id = state["scheme"]["id"]
    set_id = state["set_id"]
    parent = root / "classified" / f"set_{set_id}"
    with scheme_lock(parent, scheme_id, "Classification is already running for this scheme"):
        state = inputs(root, scheme_id, config_path, set_id=set_id)
        rows, headers, mapping = load_rows(state)
        result = classify(rows, state["config"], state["identifiers"], field_mapping=mapping)
        contents = {
            "classified.csv": csv_bytes(result.rows, headers + DERIVED_FIELDS),
            "validation_report.md": markdown_report(result.report).encode(),
            "validation_report.json": json_bytes(result.report),
            "unmapped_values.csv": csv_bytes(
                result.unmapped, ["field", "value", "count", "dso_slugs"]
            ),
        }
        manifest = dict(
            fingerprint=state["fingerprint"],
            scheme_id=scheme_id,
            set_id=set_id,
            hashes={name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
        )
        contents["run_manifest.json"] = json_bytes(manifest)

        def unchanged() -> None:
            current = inputs(root, scheme_id, config_path, set_id=set_id)
            if current["fingerprint"] != state["fingerprint"]:
                raise ValueError("Input changed during classification; run again")

        publish_generation(parent, scheme_id, contents, unchanged)
        return result


def saved_output(root: Path, scheme_id: int, *, set_id: int | None = None) -> tuple[Path, dict]:
    set_id = selected_set(root, scheme_id, set_id)
    directory = published_directory(resolve_path(root, f"classified/set_{set_id}"), scheme_id)
    manifest = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("scheme_id") != scheme_id or manifest.get("set_id") != set_id:
        raise ValueError("Classification output belongs to a different set or scheme")
    for name in OUTPUT_FILES:
        checked_file(
            root, str((directory / name).relative_to(root.resolve())), manifest["hashes"][name]
        )
    return directory, manifest


def output_status(
    root: Path, scheme_id: int, config_path: Path = CONFIG_PATH, *, set_id: int | None = None
) -> dict:
    try:
        directory, manifest = saved_output(root, scheme_id, set_id=set_id)
    except FileNotFoundError:
        return dict(has_output=False, stale=False, reason="", report=None)
    report = json.loads((directory / "validation_report.json").read_text(encoding="utf-8"))
    try:
        if any("expected" not in item for item in report["metrics"]):
            report = with_metric_expectations(report, load_config(config_path).validation)
            report["expected_values_source"] = "current_configuration"
        state = inputs(root, scheme_id, config_path, set_id=set_id)
        stale = state["fingerprint"] != manifest["fingerprint"]
        reason = (
            "Input, configuration or DSO identifiers changed; rerun classification" if stale else ""
        )
    except (ValueError, RuntimeError, OSError) as error:
        stale, reason = True, str(error)
    return dict(
        has_output=True,
        stale=stale,
        reason=reason,
        report=report,
    )
