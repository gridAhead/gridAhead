# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""PDF table extraction CLI command."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from nap_tool.data import data_dir, write_bytes
from nap_tool.database.repository import (
    documents_for_extraction,
    store_extraction,
    verify_document,
)
from nap_tool.extractor.tools import docling_tool, llmpdf_tool

TOOLS = {"docling", "llmPDF"}


def extract(
    dso: str | None = typer.Option(None, "--dso", help="DSO slug"),
    document: str | None = typer.Option(None, "--document", help="Exact title or document ID"),
    tool: str = typer.Option("docling", "--tool", help="docling or llmPDF"),
    force: bool = typer.Option(False, "--force", help="Create a new extraction version"),
    pages: str | None = typer.Option(None, "--pages", help="llmPDF page selection"),
) -> None:
    """Extract tables from downloaded, selected documents.

    Args:
        dso: Optional DSO slug.
        document: Optional exact document title or ID.
        tool: PDF extraction tool.
        force: Re-extract already processed documents.
        pages: Optional llmPDF page selection.
    """
    if tool not in TOOLS:
        raise typer.BadParameter(f"Unknown tool {tool!r}; choose docling or llmPDF")
    try:
        root = data_dir()
        rows = documents_for_extraction(root / "nap_tool.sqlite", dso, document, tool, force)
    except (RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Extraction failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not rows:
        typer.echo("No documents to extract")
        return
    failures = 0
    for row in rows:
        try:
            pdf = verify_document(root, row)
            script_path, script_hash = _snapshot_tool(root, tool, pages)
            with TemporaryDirectory(prefix="nap-extract-") as directory:
                workspace = Path(directory)
                output = workspace / "output"
                if tool == "docling":
                    docling_tool.extract(pdf, output, row["slug"], row["title"], row["hash"])
                else:
                    staged_pdf = workspace / "nap.pdf"
                    shutil.copy2(pdf, staged_pdf)
                    llmpdf_tool.extract(
                        staged_pdf, output, row["slug"], row["title"], row["hash"], pages
                    )
                count = store_extraction(
                    root / "nap_tool.sqlite",
                    root,
                    row["id"],
                    tool,
                    output,
                    script_path,
                    script_hash,
                )
            typer.echo(f"[{row['slug']}] document #{row['id']}: {count} table(s)")
        except (RuntimeError, ValueError, OSError, ImportError) as exc:
            failures += 1
            typer.echo(f"[{row['slug']}] document #{row['id']} failed: {exc}", err=True)
    if failures:
        raise typer.Exit(code=1)


def _snapshot_tool(root: Path, tool: str, pages: str | None) -> tuple[str, str]:
    """Save the adapter code and dependency version for reproducibility."""
    module = docling_tool if tool == "docling" else llmpdf_tool
    package = "docling" if tool == "docling" else "llmPDF"
    try:
        version = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        version = "not-installed"
    code = Path(module.__file__).read_text(encoding="utf-8")
    payload = json.dumps(
        {"tool": tool, "version": version, "pages": pages, "adapter_code": code},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    relative = f"scripts/extract/{tool}/{digest}.json"
    write_bytes(root, relative, payload)
    return relative, digest
