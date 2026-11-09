# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""LlamaParse Agentic table extraction using the official Llama Cloud SDK."""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from nap_tool.extractor.models import (
    ExtractedTable,
    ExtractionMetadata,
    TableRegion,
    csv_shape,
    table_filename,
    write_metadata,
)

SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def extract(
    pdf_path: Path,
    output_dir: Path,
    provider_slug: str,
    original_filename: str,
    source_sha256: str | None,
    pages: str | None = None,
) -> ExtractionMetadata:
    """Run one LlamaParse Agentic job and save its markdown tables as CSV.

    Args:
        pdf_path: Source PDF path.
        output_dir: Target ``llamaparse`` directory.
        provider_slug: Provider slug shared with the raw directory.
        original_filename: Downloader-recorded original filename.
        source_sha256: Downloader-recorded PDF hash.
        pages: Optional one-based page selection such as ``"1,3-5"``.

    Returns:
        Validated metadata for all extracted tables.

    Raises:
        FileNotFoundError: If pdf_path does not exist.
        RuntimeError: If the SDK or API key is unavailable.
    """

    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise RuntimeError("LLAMA_CLOUD_API_KEY is required for LlamaParse")
    try:
        from llama_cloud import LlamaCloud
    except ImportError as exc:
        message = "Llama Cloud SDK is not installed; run `uv sync --extra llamaparse`"
        raise RuntimeError(message) from exc

    page_ranges = {"target_pages": pages} if pages else {}
    with LlamaCloud(api_key=api_key) as client:
        result = client.parsing.parse(
            tier="agentic",
            version="latest",
            upload_file=pdf_path,
            expand=["markdown"],
            page_ranges=page_ranges,
            output_options={
                "markdown": {
                    "tables": {
                        "output_tables_as_markdown": True,
                        "merge_continued_tables": False,
                    }
                }
            },
            timeout=1800,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_csv in output_dir.glob("*.csv"):
        stale_csv.unlink()

    tables: list[ExtractedTable] = []
    if result.markdown is not None:
        for page in result.markdown.pages:
            if not page.success:
                continue
            for grid in markdown_tables(page.markdown):
                table_number = len(tables) + 1
                output_name = table_filename(original_filename, table_number)
                output_csv = output_dir / output_name
                with output_csv.open("w", encoding="utf-8", newline="") as csv_file:
                    csv.writer(csv_file).writerows(grid)
                rows, columns = csv_shape(output_csv)
                tables.append(
                    ExtractedTable(
                        table_number=table_number,
                        file=output_name,
                        pages=[page.page_number],
                        regions=[TableRegion(page=page.page_number)],
                        rows=rows,
                        columns=columns,
                        source_id=f"page-{page.page_number}-table-{table_number}",
                    )
                )

    metadata = ExtractionMetadata(
        tool="llamaparse",
        provider_slug=provider_slug,
        source_pdf=pdf_path.name,
        original_filename=original_filename,
        source_sha256=source_sha256,
        tables=tables,
    )
    write_metadata(output_dir, metadata)
    return metadata


def markdown_tables(markdown: str) -> list[list[list[str]]]:
    """Parse GitHub-style markdown pipe tables from one page.

    Args:
        markdown: Markdown returned for a single PDF page.

    Returns:
        A list of row matrices, with separator rows removed.
    """

    lines = markdown.splitlines()
    tables: list[list[list[str]]] = []
    line_index = 0
    while line_index + 1 < len(lines):
        header = _pipe_row(lines[line_index])
        separator = _pipe_row(lines[line_index + 1])
        valid_separator = separator and all(SEPARATOR_CELL.fullmatch(cell) for cell in separator)
        if not header or not valid_separator:
            line_index += 1
            continue
        rows = [header]
        line_index += 2
        while line_index < len(lines):
            row = _pipe_row(lines[line_index])
            if not row:
                break
            rows.append(row)
            line_index += 1
        tables.append(rows)
    return tables


def _pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if "|" not in stripped:
        return []
    return [cell.strip().replace("<br>", "\n") for cell in stripped.strip("|").split("|")]
