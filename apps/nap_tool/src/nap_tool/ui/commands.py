# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""CLI entry point for the overview UI."""

from __future__ import annotations

import sqlite3

import typer
import uvicorn

from nap_tool.database.schema import DB_VERSION
from nap_tool.ui.server import create_app


def ui(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, min=1, max=65535, help="HTTP port"),
) -> None:
    """Start the overview UI.

    Args:
        host: Network interface to bind.
        port: HTTP port.

    Raises:
        typer.Exit: If the data repository or built UI is unavailable.
    """
    try:
        app = create_app()
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        typer.echo(f"UI cannot start: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"DB_VERSION {DB_VERSION}: nap_data matches this nap_tool")
    typer.echo(f"Overview page: http://{host}:{port}/ui/overview")
    uvicorn.run(app, host=host, port=port)
