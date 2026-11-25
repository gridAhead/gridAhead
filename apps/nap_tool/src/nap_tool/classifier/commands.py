# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""CLI shell for semantic classification and location proposals."""

import json
import sqlite3
import sys
from pathlib import Path

import typer

from nap_tool.data import data_dir

from .config import CONFIG_PATH
from .service import add_proposals, run, source_records

propose_app = typer.Typer(help="Location proposals for classification (ADR-0008).")


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
