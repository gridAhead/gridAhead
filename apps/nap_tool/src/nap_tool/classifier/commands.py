# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""CLI shell for semantic classification."""

from pathlib import Path

import typer

from nap_tool.data import data_dir

from .config import CONFIG_PATH
from .service import run


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
