# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Discovery and PDF download CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.error import URLError

import typer

from nap_tool.config import load_providers
from nap_tool.data import data_dir
from nap_tool.database.repository import (
    Candidate,
    create_download_run,
    documents_for_download,
    record_download,
    store_candidates,
)
from nap_tool.downloader.sources import (
    _read_url,
    discover_configured,
    discover_vnbdigital,
    download_vnbdigital_pdf,
)
from nap_tool.dso_identifiers import sync_dso_identifiers


def discover(
    dso: str | None = typer.Option(None, "--dso", help="DSO slug"),
    document: str | None = typer.Option(None, "--document", help="Exact document title"),
    config_path: Path = typer.Option(Path("config/providers.yaml"), help="Provider registry"),
) -> None:
    """Register all source documents without downloading PDFs.

    Args:
        dso: Optional DSO slug.
        document: Optional exact document title.
        config_path: Provider registry path.
    """
    try:
        root = data_dir()
        config = load_providers(config_path)
        candidates: list[Candidate] = []
        if config.vnbdigital.enabled:
            for item in discover_vnbdigital(config.vnbdigital):
                if dso is not None and item["provider_slug"] != dso:
                    continue
                candidates.append(
                    Candidate(
                        provider_slug=item["provider_slug"],
                        provider_name=item["provider_name"],
                        source="vnbdigital",
                        source_document_id=item["document_id"],
                        title=item["document_name"],
                        source_url=item["source_url"],
                        version=str(item["current_from"]) if item["current_from"] else None,
                    )
                )
        for configured in config.providers:
            if dso is not None and configured.slug != dso:
                continue
            for title, url in discover_configured(configured, config.hub):
                candidates.append(
                    Candidate(
                        configured.slug,
                        configured.name,
                        configured.source_type.value,
                        None,
                        title,
                        url,
                    )
                )
        if document is not None:
            candidates = [item for item in candidates if item.title == document]
        created, known = store_candidates(root / "nap_tool.sqlite", candidates)
    except (RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Discovery failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Discovered {len(candidates)} document(s): {created} new, {known} known")
    try:
        result = sync_dso_identifiers(root / "nap_tool.sqlite")
        typer.echo(f"DSO identifiers: {result}")
    except (RuntimeError, OSError, ValueError, URLError) as exc:
        typer.echo(f"DSO identifier lookup unavailable: {exc}", err=True)


def sync_identifiers() -> None:
    """Fill missing DSO identifiers from the public MaStR and BDEW registries."""
    try:
        result = sync_dso_identifiers(data_dir() / "nap_tool.sqlite")
    except (RuntimeError, OSError, ValueError, URLError) as exc:
        typer.echo(f"DSO identifier sync failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"DSO identifiers: {result}")


def download(
    dso: str | None = typer.Option(None, "--dso", help="DSO slug"),
    document: str | None = typer.Option(None, "--document", help="Exact title or document ID"),
    force: bool = typer.Option(False, "--force", help="Refresh already downloaded PDFs"),
) -> None:
    """Download pending source documents.

    Args:
        dso: Optional DSO slug.
        document: Optional exact document title or ID.
        force: Refresh already downloaded documents.
    """
    try:
        root = data_dir()
        rows = documents_for_download(root / "nap_tool.sqlite", dso, document, force)
    except (RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Download failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not rows:
        typer.echo("No documents to download; run `nap-tool discover` first")
        return
    run_id = create_download_run(root / "nap_tool.sqlite", " ".join(sys.argv))
    failures = 0
    for row in rows:
        try:
            if row["source_url"] is None:
                raise ValueError("Document has no download URL")
            content = (
                download_vnbdigital_pdf(row["source_url"])
                if row["source"] == "vnbdigital"
                else _read_url(row["source_url"])
            )
            document_id, created = record_download(
                root / "nap_tool.sqlite", root, row, content, run_id
            )
            action = "downloaded" if created else "already stored"
            typer.echo(f"[{row['slug']}] document #{document_id}: {action}")
        except (RuntimeError, ValueError, OSError) as exc:
            failures += 1
            typer.echo(f"[{row['slug']}] document #{row['id']} failed: {exc}", err=True)
    if failures:
        raise typer.Exit(code=1)
