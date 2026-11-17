# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Warn when a Git checkout is running with stale optional dependencies."""

import tomllib
from importlib import metadata
from pathlib import Path

import typer


def warn_llmpdf_version() -> None:
    """Compare llmPDF with the checkout's pin, without querying the network."""
    try:
        installed = metadata.version("llmPDF")
    except metadata.PackageNotFoundError:
        return

    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        requirements = project["project"]["optional-dependencies"].get("llmpdf", [])
    else:
        requirements = metadata.requires("nap-tool") or []

    for requirement in requirements:
        name, separator, tail = requirement.partition("==")
        if separator and name.strip().lower() == "llmpdf":
            expected = tail.split(";", 1)[0].strip()
            if installed != expected:
                typer.echo(
                    f"Warning: installed llmPDF {installed}; nap-tool requires {expected}. "
                    "Run `uv sync --extra llmpdf --locked` in the nap-tool project "
                    "(or `uv sync --extra all-extractors --locked` for all extractors).",
                    err=True,
                )
            return
