# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Shared metadata models for table extractors."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


def table_filename(original_filename: str, table_number: int) -> str:
    """Build the standard CSV filename for one extracted table.

    Args:
        original_filename: Original PDF filename recorded by the downloader.
        table_number: One-based table number.

    Returns:
        Filename in ``<original_filename_stem>_table_<n>.csv`` format.

    Raises:
        ValueError: If the filename stem is empty or the table number is invalid.
    """

    stem = Path(original_filename).stem.strip()
    if not stem:
        raise ValueError("Original PDF filename must have a non-empty stem")
    if table_number < 1:
        raise ValueError("Table number must be positive")
    return f"{stem}_table_{table_number}.csv"


class TableRegion(BaseModel):
    """One source region occupied by an extracted table.

    Attributes:
        page: One-based PDF page number.
        bbox: Optional PDF bounding box in ``[x0, y0, x1, y1]`` order.
    """

    page: int
    bbox: list[float] | None = None


class ExtractedTable(BaseModel):
    """Metadata for one CSV table produced by an extraction tool.

    Attributes:
        table_number: One-based table number within the tool output.
        file: CSV filename relative to the tool directory.
        pages: Sorted one-based source page numbers.
        regions: Source regions used to produce the table.
        rows: Number of CSV rows, including the header.
        columns: Maximum number of CSV columns.
        title: Optional table title from the extractor.
        source_id: Extractor-specific table identifier.
        status: Extractor-specific validation status.
        merged: Whether multiple source regions were merged into this CSV.
    """

    table_number: int
    file: str
    pages: list[int] = Field(default_factory=list)
    regions: list[TableRegion] = Field(default_factory=list)
    rows: int
    columns: int
    title: str | None = None
    source_id: str | None = None
    status: str = "extracted"
    merged: bool = False


class ExtractionMetadata(BaseModel):
    """Metadata written beside one extractor's CSV files.

    Attributes:
        tool: Stable extractor directory name.
        provider_slug: Provider identifier shared with ``data/raw``.
        source_pdf: Stable PDF filename used for extraction.
        original_filename: Original filename recorded by the downloader.
        source_sha256: Source PDF SHA-256 from downloader metadata.
        generated_at: UTC timestamp for this output.
        tables: Extracted table records.
        imported_from: Existing-result directory for imported output.
        source_markdown: Markdown file containing the imported tool output.
        error: Explicit extraction failure, if the tool did not complete.
    """

    schema_version: str = "nap-tool/extraction-metadata@1.0"
    tool: str
    provider_slug: str
    source_pdf: str
    original_filename: str
    source_sha256: str | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    tables: list[ExtractedTable] = Field(default_factory=list)
    imported_from: str | None = None
    source_markdown: str | None = None
    error: str | None = None


class LlmpdfDoclingTable(BaseModel):
    """One Docling table retained by llmPDF's native result.

    Attributes:
        id: llmPDF's stable Docling table identifier.
        page: One-based source page number.
        normalized_csv: Corresponding Docling CSV relative to the result directory.
        status: llmPDF's disposition of the Docling table.
        replacement_table_ids: llmPDF tables that replaced or merged this table.
        bbox: Optional source-page bounding box.
    """

    id: str
    page: int
    normalized_csv: str | None = None
    status: str | None = None
    replacement_table_ids: list[str] = Field(default_factory=list)
    bbox: dict[str, float] | None = None


class LlmpdfSource(BaseModel):
    """Source PDF identity embedded in a compact llmPDF result map."""

    file: str
    sha256: str
    page_count: int = 0
    selected_pages: list[int] = Field(default_factory=list)


class LlmpdfOutput(BaseModel):
    """Generated Markdown identity embedded in a compact llmPDF result map."""

    markdown: str = "output.md"
    sha256: str


class LlmpdfTableMapping(BaseModel):
    """Relationship between one llmPDF CSV and its Docling inputs.

    Attributes:
        id: llmPDF's stable table identifier.
        normalized_csv: Corresponding nap-tool CSV path relative to the result directory.
        page: Primary one-based PDF page.
        source_pages: One-based PDF pages used by the table.
        name: Optional table title.
        header_rows: Number of table header rows.
        bbox: Optional bounding box on the primary page.
        page_bboxes: Optional bounding boxes indexed by source page.
        docling_table_ids: llmPDF Docling table identifiers used by this table.
        lineage_action: llmPDF's merge/replacement action when available.
    """

    id: str
    normalized_csv: str
    page: int
    source_pages: list[int] = Field(default_factory=list)
    name: str | None = None
    header_rows: int = 1
    bbox: dict[str, float] | None = None
    page_bboxes: dict[str, dict[str, float] | None] = Field(default_factory=dict)
    docling_table_ids: list[str] = Field(default_factory=list)
    lineage_action: str | None = None


class LlmpdfResultMap(BaseModel):
    """Portable map for an llmPDF result and its retained Docling lineage.

    Attributes:
        schema_version: Versioned nap-tool map contract.
        provider_slug: Provider identifier shared with ``data/raw``.
        source: Source PDF identity and page selection.
        output: Generated Markdown identity.
        tables: One entry for each normalized llmPDF CSV.
        docling_tables: Docling source tables retained by llmPDF.
        source_url: Downloader source URL when available.
        document_id: Downloader document identifier when available.
    """

    schema_version: str = "nap-tool/llmpdf-result-map@3.0"
    provider_slug: str
    source: LlmpdfSource
    output: LlmpdfOutput
    tables: list[LlmpdfTableMapping] = Field(default_factory=list)
    docling_tables: list[LlmpdfDoclingTable] = Field(default_factory=list)
    source_url: str | None = None
    document_id: str | None = None


def csv_shape(csv_path: Path) -> tuple[int, int]:
    """Return the row count and maximum column count of a CSV file.

    Args:
        csv_path: CSV file to inspect.

    Returns:
        Tuple containing row count and maximum column count.
    """

    with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.reader(csv_file))
    return len(rows), max((len(row) for row in rows), default=0)


def write_metadata(output_dir: Path, metadata: ExtractionMetadata) -> Path:
    """Write extraction metadata atomically.

    Args:
        output_dir: Extractor output directory.
        metadata: Validated metadata to serialize.

    Returns:
        Path to the written metadata file.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "metadata.json"
    temporary_path = output_dir / ".metadata.json.tmp"
    temporary_path.write_text(
        json.dumps(metadata.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(metadata_path)
    return metadata_path
