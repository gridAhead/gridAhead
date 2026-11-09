# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Adapter for the published llmPDF PDF conversion package."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from nap_tool.extractor.models import (
    ExtractedTable,
    ExtractionMetadata,
    LlmpdfDoclingTable,
    LlmpdfOutput,
    LlmpdfResultMap,
    LlmpdfSource,
    LlmpdfTableMapping,
    TableRegion,
    csv_shape,
    table_filename,
    write_metadata,
)


def native_result_dir(output_dir: Path) -> Path:
    """Return the stable llmPDF result directory for one provider."""

    return output_dir / "result" / "nap"


def result_map_path(result_dir: Path) -> Path:
    """Return the nap-tool map stored beside an llmPDF native result.

    Args:
        result_dir: Native llmPDF result directory.

    Returns:
        Path of the generated map file.
    """

    return result_dir / "map.json"


def compact_result(result_dir: Path) -> dict[str, int]:
    """Remove native llmPDF artifacts that the nap-tool Review UI does not use.

    The compact result retains Markdown, nap-tool's self-contained lineage map,
    and review drafts/history. Table comparison reads normalized llmPDF and
    Docling CSVs outside this directory.

    Args:
        result_dir: Native ``llmPDF/result/nap`` directory to compact.

    Returns:
        Counts of removed files and bytes.

    Raises:
        FileNotFoundError: If the required map or Markdown is missing.
    """

    map_path = result_map_path(result_dir)
    output_path = result_dir / "output.md"
    if not map_path.is_file():
        raise FileNotFoundError(map_path)
    if not output_path.is_file():
        raise FileNotFoundError(output_path)
    before = _tree_size(result_dir)
    assets_dir = result_dir / "assets"
    if assets_dir.exists():
        _remove_path(assets_dir)
    work_dir = result_dir / "work"
    if work_dir.is_dir():
        for child in work_dir.iterdir():
            if child.name != "review":
                _remove_path(child)
        _compact_review_state(work_dir / "review")
        if not any(work_dir.iterdir()):
            work_dir.rmdir()
    after = _tree_size(result_dir)
    return {"removed_files": max(0, before[0] - after[0]), "removed_bytes": before[1] - after[1]}


def extract(
    pdf_path: Path,
    output_dir: Path,
    provider_slug: str,
    original_filename: str,
    source_sha256: str | None,
    pages: str | None = None,
) -> ExtractionMetadata:
    """Run llmPDF and expose its tables through nap-tool's CSV contract."""

    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    initial_sha256 = _sha256_file(pdf_path)
    if source_sha256 is not None and source_sha256 != initial_sha256:
        raise RuntimeError(f"Source PDF hash does not match downloader metadata: {pdf_path}")
    try:
        from llmpdf import ConversionError, ConvertOptions, convert
    except ImportError as exc:
        raise RuntimeError("llmPDF is not installed; run `uv sync --extra llmpdf`") from exc

    try:
        result = convert(
            ConvertOptions(
                pdf=pdf_path,
                output_root=output_dir,
                batch_id="result",
                pages=pages,
            )
        )
    except (ConversionError, OSError, ValueError) as exc:
        if _sha256_file(pdf_path) != initial_sha256:
            raise RuntimeError(f"llmPDF modified the source PDF: {pdf_path}") from exc
        raise RuntimeError(f"llmPDF failed to convert {pdf_path.name}: {exc}") from exc

    if _sha256_file(pdf_path) != initial_sha256:
        raise RuntimeError(f"llmPDF modified the source PDF: {pdf_path}")

    expected_result = native_result_dir(output_dir)
    if result.output_dir.resolve() != expected_result.resolve():
        raise RuntimeError(f"llmPDF returned an unexpected result directory: {result.output_dir}")
    return normalize_result(
        expected_result,
        output_dir,
        provider_slug,
        original_filename,
        initial_sha256,
    )


def normalize_result(
    result_dir: Path,
    output_dir: Path,
    provider_slug: str,
    original_filename: str,
    source_sha256: str | None,
) -> ExtractionMetadata:
    """Copy llmPDF table CSVs into nap-tool's stable normalized layout."""

    payload = _read_result_metadata(result_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_csv in output_dir.glob("*.csv"):
        stale_csv.unlink()

    tables: list[ExtractedTable] = []
    for raw_table in payload.get("tables", []):
        if not isinstance(raw_table, dict) or not raw_table.get("csv"):
            continue
        source_csv = _safe_result_path(result_dir, str(raw_table["csv"]))
        table_number = len(tables) + 1
        output_name = table_filename(original_filename, table_number)
        output_csv = output_dir / output_name
        shutil.copy2(source_csv, output_csv)
        rows, columns = csv_shape(output_csv)
        pages = sorted(
            {int(page) for page in raw_table.get("source_pages", [raw_table.get("page", 1)])}
        )
        bbox = _bbox_values(raw_table.get("bbox"))
        primary_page = int(raw_table.get("page", pages[0] if pages else 1))
        tables.append(
            ExtractedTable(
                table_number=table_number,
                file=output_name,
                pages=pages,
                regions=[
                    TableRegion(page=page, bbox=bbox if page == primary_page else None)
                    for page in pages
                ],
                rows=rows,
                columns=columns,
                title=str(raw_table["name"]) if raw_table.get("name") else None,
                source_id=str(raw_table["id"]) if raw_table.get("id") else None,
                status="extracted",
                merged=len(pages) > 1,
            )
        )

    metadata = ExtractionMetadata(
        tool="llmPDF",
        provider_slug=provider_slug,
        source_pdf="nap.pdf",
        original_filename=original_filename,
        source_sha256=source_sha256,
        tables=tables,
    )
    write_metadata(output_dir, metadata)
    write_result_map(result_dir, output_dir, provider_slug, source_sha256, original_filename)
    compact_result(result_dir)
    return metadata


def write_result_map(
    result_dir: Path,
    output_dir: Path,
    provider_slug: str,
    source_sha256: str | None,
    original_filename: str | None = None,
) -> Path:
    """Write the llmPDF-to-Docling lineage map after a successful extraction.

    Args:
        result_dir: Native llmPDF result directory.
        output_dir: Normalized nap-tool llmPDF output directory.
        provider_slug: Provider slug shared with the raw directory.
        source_sha256: SHA-256 of the PDF used for extraction.
        original_filename: Downloader-recorded PDF filename used for normalized CSVs.

    Returns:
        Path of the atomically written map file.

    Raises:
        RuntimeError: If llmPDF metadata is invalid or does not identify the source PDF.
    """

    payload = _read_result_metadata(result_dir)
    native_source = payload.get("source")
    if not isinstance(native_source, dict):
        raise RuntimeError(f"llmPDF metadata has no source object: {result_dir}")
    native_sha256 = native_source.get("sha256")
    source_file = str(native_source.get("file") or "nap.pdf")
    normalized_source_file = original_filename or source_file
    resolved_sha256 = str(source_sha256 or native_sha256 or "")
    if not resolved_sha256:
        raise RuntimeError(f"llmPDF metadata has no source SHA-256: {result_dir}")
    if source_sha256 is not None and native_sha256 is not None and source_sha256 != native_sha256:
        raise RuntimeError(f"llmPDF metadata does not match source PDF: {result_dir}")

    output_path = result_dir / "output.md"
    if not output_path.is_file():
        raise FileNotFoundError(output_path)
    output_path.write_text(
        _remove_image_blocks(output_path.read_text(encoding="utf-8")), encoding="utf-8"
    )

    tables: list[LlmpdfTableMapping] = []
    for raw_table in payload.get("tables", []):
        if not isinstance(raw_table, dict) or not raw_table.get("id") or not raw_table.get("csv"):
            continue
        table_number = len(tables) + 1
        source_pages = _source_pages(raw_table)
        lineage = raw_table.get("lineage")
        docling_table_ids = (
            [str(value) for value in lineage.get("docling_table_ids", [])]
            if isinstance(lineage, dict)
            else []
        )
        tables.append(
            LlmpdfTableMapping(
                id=str(raw_table["id"]),
                normalized_csv=f"../../{table_filename(normalized_source_file, table_number)}",
                page=int(raw_table.get("page", source_pages[0] if source_pages else 1)),
                source_pages=source_pages,
                name=str(raw_table["name"]) if raw_table.get("name") else None,
                header_rows=int(raw_table.get("header_rows", 1)),
                bbox=_bbox_object(raw_table.get("bbox")),
                page_bboxes=_page_bboxes(raw_table.get("page_bboxes")),
                docling_table_ids=docling_table_ids,
                lineage_action=(
                    str(lineage["action"])
                    if isinstance(lineage, dict) and lineage.get("action")
                    else None
                ),
            )
        )

    docling_files = _docling_normalized_files(result_dir)
    docling_tables: list[LlmpdfDoclingTable] = []
    for raw_table in payload.get("docling_tables", []):
        valid_table = (
            isinstance(raw_table, dict)
            and raw_table.get("id")
            and raw_table.get("page") is not None
        )
        if not valid_table:
            continue
        docling_tables.append(
            LlmpdfDoclingTable(
                id=str(raw_table["id"]),
                page=int(raw_table["page"]),
                normalized_csv=docling_files.get(str(raw_table.get("source_ref") or "")),
                status=str(raw_table["status"]) if raw_table.get("status") else None,
                replacement_table_ids=[
                    str(value) for value in raw_table.get("replacement_table_ids", [])
                ],
                bbox=_bbox_object(raw_table.get("bbox")),
            )
        )

    source_identity = _source_identity(result_dir, provider_slug)
    page_count = int(native_source.get("page_count") or 0)
    selected_pages_value = native_source.get("selected_pages")
    selected_pages = (
        [int(page) for page in selected_pages_value]
        if isinstance(selected_pages_value, list)
        else list(range(1, page_count + 1))
    )
    result_map = LlmpdfResultMap(
        provider_slug=provider_slug,
        source=LlmpdfSource(
            file=source_file,
            sha256=resolved_sha256,
            page_count=page_count,
            selected_pages=selected_pages,
        ),
        output=LlmpdfOutput(sha256=_sha256_file(output_path)),
        tables=tables,
        docling_tables=docling_tables,
        source_url=source_identity.get("source_url"),
        document_id=source_identity.get("document_id"),
    )
    map_path = result_map_path(result_dir)
    temporary_path = map_path.with_suffix(".json.tmp")
    temporary_path.write_text(result_map.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(map_path)
    return map_path


def _safe_result_path(result_dir: Path, relative: str) -> Path:
    path = (result_dir / relative).resolve()
    root = result_dir.resolve()
    if root not in path.parents or not path.is_file():
        raise RuntimeError(f"llmPDF table asset is unavailable: {relative}")
    return path


def _read_result_metadata(result_dir: Path) -> dict[str, object]:
    """Load and validate llmPDF's native metadata object."""

    metadata_path = result_dir / "assets" / "metadata.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid llmPDF metadata in {metadata_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object in {metadata_path}")
    return payload


def _source_pages(raw_table: dict[str, object]) -> list[int]:
    """Return a normalized source-page list from one native table record."""

    values = raw_table.get("source_pages", [raw_table.get("page", 1)])
    if not isinstance(values, list):
        values = [values]
    return sorted({int(value) for value in values if value is not None})


def _bbox_values(value: object) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    keys = ("x0", "top", "x1", "bottom")
    if any(value.get(key) is None for key in keys):
        return None
    return [float(value[key]) for key in keys]


def _bbox_object(value: object) -> dict[str, float] | None:
    """Return a normalized llmPDF bounding-box object."""

    if not isinstance(value, dict):
        return None
    keys = ("x0", "top", "x1", "bottom")
    if any(value.get(key) is None for key in keys):
        return None
    return {key: float(value[key]) for key in keys}


def _page_bboxes(value: object) -> dict[str, dict[str, float] | None]:
    """Return normalized table bounding boxes indexed by page."""

    if not isinstance(value, dict):
        return {}
    return {str(page): _bbox_object(bbox) for page, bbox in value.items()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_image_blocks(markdown: str) -> str:
    """Remove image-only Markdown blocks while preserving page markers."""

    return re.sub(
        r"(?ms)^\s*<!-- image:[^\n]* -->\s*\n.*?^\s*<!-- /image:[^\n]* -->\s*(?:\n|$)",
        "",
        markdown,
    )


def _compact_review_state(review_dir: Path) -> None:
    """Remove superseded table snapshots while retaining drafts and audit JSON."""

    if not review_dir.is_dir():
        return
    source_dir = review_dir / "source"
    if source_dir.exists():
        _remove_path(source_dir)
    history_dir = review_dir / "history"
    if history_dir.is_dir():
        for history in history_dir.iterdir():
            if history.is_dir():
                for child in history.iterdir():
                    if child.name != "draft.json":
                        _remove_path(child)
                if not any(history.iterdir()):
                    history.rmdir()
        if not any(history_dir.iterdir()):
            history_dir.rmdir()


def _docling_normalized_files(result_dir: Path) -> dict[str, str]:
    """Map Docling source IDs to normalized CSV paths for this provider."""

    docling_dir = result_dir.parents[2] / "docling"
    metadata_path = docling_dir / "metadata.json"
    if not metadata_path.is_file():
        return {}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        return {}
    files: dict[str, str] = {}
    for table in metadata.get("tables", []):
        if not isinstance(table, dict) or not table.get("source_id") or not table.get("file"):
            continue
        csv_path = docling_dir / str(table["file"])
        if csv_path.is_file():
            files[str(table["source_id"])] = f"../../../docling/{table['file']}"
    return files


def _source_identity(result_dir: Path, provider_slug: str) -> dict[str, str]:
    """Load source URL and document ID from existing map or raw metadata."""

    values: dict[str, str] = {}
    map_path = result_map_path(result_dir)
    if map_path.is_file():
        existing = json.loads(map_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            for key in ("source_url", "document_id"):
                if isinstance(existing.get(key), str):
                    values[key] = str(existing[key])
    data_dir = result_dir.parents[5] if len(result_dir.parents) > 5 else None
    raw_metadata = data_dir / "raw" / provider_slug / "metadata.json" if data_dir else None
    if raw_metadata is not None and raw_metadata.is_file():
        metadata = json.loads(raw_metadata.read_text(encoding="utf-8"))
        if isinstance(metadata, dict):
            for key in ("source_url", "document_id"):
                if isinstance(metadata.get(key), str):
                    values[key] = str(metadata[key])
    return values


def _remove_path(path: Path) -> None:
    """Remove one known result artifact path."""

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _tree_size(root: Path) -> tuple[int, int]:
    """Return logical file count and byte size below a result directory."""

    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)
