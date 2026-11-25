# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""CLI shell for semantic classification and location proposals."""

import codecs
import csv
import json
import sqlite3
import sys
from pathlib import Path

import typer

from nap_tool.data import data_dir

from .config import CONFIG_PATH
from .service import (
    REVIEW_COLUMNS,
    add_proposals,
    csv_bytes,
    import_review,
    review_rows,
    run,
    source_records,
)

propose_app = typer.Typer(help="Location proposals for classification (ADR-0008).")
review_app = typer.Typer(help="Human review of proposals through a CSV round trip.")
propose_app.add_typer(review_app, name="review")


def classify_command(
    scheme_id: int = typer.Option(..., min=1, help="Harmonization scheme to classify"),
    set_id: int | None = typer.Option(
        None, min=1, help="Set to classify (defaults to the scheme's initial set)"
    ),
    config_path: Path = typer.Option(CONFIG_PATH, help="Classification YAML"),
) -> None:
    try:
        root = data_dir()
        result = run(root, scheme_id, config_path=config_path, set_id=set_id)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Classification error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Rows: {result.report['rows']} · {result.report['record_types']}")
    for field, ratio in result.report["coverage"].items():
        typer.echo(f"{field}: {ratio:.1%}")
    typer.echo(f"Validation: {result.report['status']} · Output: {root / 'classified'}")
    raise typer.Exit({"pass": 0, "warn": 3, "fail": 4}[result.report["status"]])


@propose_app.command(name="add")
def propose_add_command(
    scheme_id: int = typer.Option(..., min=1, help="Harmonization scheme of the records"),
    set_id: int = typer.Option(..., min=1, help="Set of the records"),
    model: str = typer.Option(..., help="Model that made the proposals"),
    skill_version: str = typer.Option(..., help="Version of the Skill that guided the model"),
) -> None:
    """Check proposal JSON lines from stdin, store passing ones and report every line."""
    try:
        root = data_dir()
        records = source_records(root, scheme_id, set_id)
        report = add_proposals(root, records, sys.stdin.read().splitlines(), model, skill_version)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        typer.echo(f"Proposal error: {error}", err=True)
        raise typer.Exit(1) from error
    for line in report:
        typer.echo(json.dumps(line, ensure_ascii=False))


@review_app.command(name="export")
def review_export_command(
    path: Path = typer.Argument(..., help="Review CSV to write"),
    scheme_id: int = typer.Option(..., min=1, help="Harmonization scheme of the records"),
    set_id: int = typer.Option(..., min=1, help="Set of the records"),
    config_path: Path = typer.Option(CONFIG_PATH, help="Classification YAML, as for classify"),
) -> None:
    """Write conflicting proposals and an audit sample of auto-accepted ones to a CSV."""
    try:
        rows = review_rows(data_dir(), scheme_id, set_id, config_path)
        # A BOM lets spreadsheet programs read the CSV as UTF-8.
        path.write_bytes(codecs.BOM_UTF8 + csv_bytes(rows, REVIEW_COLUMNS))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        typer.echo(f"Review error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"{len(rows)} proposals to review: {path}")


@review_app.command(name="import")
def review_import_command(
    path: Path = typer.Argument(..., help="Review CSV with filled decision column"),
) -> None:
    """Store accept, reject or corrected-name decisions; an invalid row stores nothing."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            counts = import_review(data_dir(), csv.DictReader(stream))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        typer.echo(f"Review error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(", ".join(f"{count} {status}" for status, count in counts.items()))
