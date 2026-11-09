# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Docling-backed PDF table extraction."""

from __future__ import annotations

from pathlib import Path

from nap_tool.extractor.models import (
    ExtractedTable,
    ExtractionMetadata,
    TableRegion,
    csv_shape,
    table_filename,
    write_metadata,
)


def extract(
    pdf_path: Path,
    output_dir: Path,
    provider_slug: str,
    original_filename: str,
    source_sha256: str | None,
) -> ExtractionMetadata:
    """Extract PDF tables with Docling and write normalized CSV output.

    Args:
        pdf_path: Source PDF path.
        output_dir: Target ``docling`` directory.
        provider_slug: Provider slug shared with the raw directory.
        original_filename: Downloader-recorded original filename.
        source_sha256: Downloader-recorded PDF hash.

    Returns:
        Validated metadata for all extracted tables.

    Raises:
        FileNotFoundError: If pdf_path does not exist.
        RuntimeError: If Docling is not installed or conversion fails.
    """

    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError("Docling is not installed; run `uv sync --extra docling`") from exc

    try:
        result = DocumentConverter().convert(pdf_path)
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Docling failed to convert {pdf_path.name}: {exc}") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_csv in output_dir.glob("*.csv"):
        stale_csv.unlink()

    tables: list[ExtractedTable] = []
    for table_number, table in enumerate(result.document.tables, start=1):
        output_name = table_filename(original_filename, table_number)
        output_csv = output_dir / output_name
        dataframe = table.export_to_dataframe(doc=result.document)
        dataframe.to_csv(output_csv, index=False)
        rows, columns = csv_shape(output_csv)
        regions = [
            TableRegion(page=item.page_no, bbox=_bbox_values(item.bbox)) for item in table.prov
        ]
        tables.append(
            ExtractedTable(
                table_number=table_number,
                file=output_name,
                pages=sorted({region.page for region in regions}),
                regions=regions,
                rows=rows,
                columns=columns,
                source_id=getattr(table, "self_ref", None),
                merged=len(regions) > 1,
            )
        )

    metadata = ExtractionMetadata(
        tool="docling",
        provider_slug=provider_slug,
        source_pdf=pdf_path.name,
        original_filename=original_filename,
        source_sha256=source_sha256,
        tables=tables,
    )
    write_metadata(output_dir, metadata)
    return metadata


def _bbox_values(bbox: object) -> list[float] | None:
    values = [getattr(bbox, name, None) for name in ("l", "t", "r", "b")]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values]
