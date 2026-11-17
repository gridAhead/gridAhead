# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for adapting llmPDF results to nap-tool's stable table format."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from nap_tool.extractor.tools.llmpdf_tool import (
    extract,
    native_result_dir,
    normalize_result,
    result_map_path,
)


def test_extract_calls_published_sdk_and_forwards_pages(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "raw/grid/nap.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    output_dir = tmp_path / "extracted/grid/llmPDF"
    captured = {}

    def fake_convert(options):
        captured["options"] = options
        result_dir = native_result_dir(output_dir)
        table_csv = result_dir / "assets/tables/table-0001.csv"
        table_csv.parent.mkdir(parents=True)
        table_csv.write_text("A\n1\n", encoding="utf-8")
        (result_dir / "assets/metadata.json").write_text(
            json.dumps(
                {
                    "source": {
                        "file": "original.pdf",
                        "sha256": hashlib.sha256(b"%PDF-test").hexdigest(),
                        "page_count": 3,
                        "selected_pages": [3],
                    },
                    "tables": [
                        {
                            "id": "table-0001",
                            "page": 3,
                            "source_pages": [3],
                            "csv": "assets/tables/table-0001.csv",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (result_dir / "output.md").write_text("<!-- page:3 -->\n", encoding="utf-8")
        image = result_dir / "assets/images/image-0001.png"
        image.parent.mkdir()
        image.write_bytes(b"unused image")
        cache = result_dir / "work/cache/state.json"
        cache.parent.mkdir(parents=True)
        cache.write_text("{}", encoding="utf-8")
        draft = result_dir / "work/review/draft.json"
        draft.parent.mkdir(parents=True)
        draft.write_text('{"tables": {}}', encoding="utf-8")
        return SimpleNamespace(output_dir=result_dir)

    class FakeConvertOptions:
        def __init__(self, **values):
            vars(self).update(values)

    monkeypatch.setitem(
        sys.modules,
        "llmpdf",
        SimpleNamespace(
            ConversionError=RuntimeError,
            ConvertOptions=FakeConvertOptions,
            convert=fake_convert,
        ),
    )

    source_sha256 = hashlib.sha256(b"%PDF-test").hexdigest()
    metadata = extract(pdf, output_dir, "grid", "original.pdf", source_sha256, "3")

    options = captured["options"]
    assert options.pdf == pdf
    assert options.output_root == output_dir
    assert options.batch_id == "result"
    assert options.pages == "3"
    assert metadata.tables[0].file == "original_table_1.csv"
    assert metadata.source_sha256 == source_sha256
    result_map = json.loads(
        result_map_path(native_result_dir(output_dir)).read_text(encoding="utf-8")
    )
    assert result_map["tables"][0]["normalized_csv"] == "../../original_table_1.csv"
    assert result_map["schema_version"] == "nap-tool/llmpdf-result-map@3.0"
    assert not (native_result_dir(output_dir) / "assets").exists()
    assert not (native_result_dir(output_dir) / "work/cache").exists()
    assert (native_result_dir(output_dir) / "work/review/draft.json").is_file()


def test_normalize_result_writes_nap_table_csv_and_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "extracted/grid/llmPDF"
    docling_dir = output_dir.parent / "docling"
    docling_dir.mkdir(parents=True)
    (docling_dir / "nap_table_1.csv").write_text("A,B\n1,2\n", encoding="utf-8")
    (docling_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source": {
                    "file": "original.pdf",
                    "sha256": "abc123",
                    "page_count": 3,
                    "selected_pages": [2, 3],
                },
                "tables": [
                    {
                        "source_id": "#/tables/3",
                        "file": "nap_table_1.csv",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result_dir = native_result_dir(output_dir)
    source_csv = result_dir / "assets/tables/table-0007.csv"
    source_csv.parent.mkdir(parents=True)
    source_csv.write_text("A,B\n1,2\n", encoding="utf-8")
    (result_dir / "assets/metadata.json").write_text(
        json.dumps(
            {
                "source": {
                    "file": "original.pdf",
                    "sha256": "abc123",
                    "page_count": 3,
                    "selected_pages": [2, 3],
                },
                "tables": [
                    {
                        "id": "table-0007",
                        "name": "Capacity",
                        "page": 2,
                        "source_pages": [2, 3],
                        "bbox": {"x0": 1, "top": 2, "x1": 10, "bottom": 20},
                        "csv": "assets/tables/table-0007.csv",
                        "lineage": {"docling_table_ids": ["docling-table-0003"]},
                    }
                ],
                "docling_tables": [
                    {
                        "id": "docling-table-0003",
                        "page": 2,
                        "source_ref": "#/tables/3",
                        "markdown": "assets/docling-tables/docling-table-0003.md",
                        "status": "replaced",
                        "replacement_table_ids": ["table-0007"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "output.md").write_text("<!-- page:2 -->\n", encoding="utf-8")

    metadata = normalize_result(
        result_dir,
        output_dir,
        "grid",
        "original.pdf",
        "abc123",
    )

    assert (output_dir / "original_table_1.csv").read_text(encoding="utf-8") == ("A,B\n1,2\n")
    assert metadata.tool == "llmPDF"
    assert metadata.tables[0].pages == [2, 3]
    assert metadata.tables[0].merged is True
    payload = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert payload["tables"][0]["file"] == "original_table_1.csv"
    result_map = json.loads(result_map_path(result_dir).read_text(encoding="utf-8"))
    assert result_map["source"]["sha256"] == "abc123"
    assert result_map["tables"][0]["id"] == "table-0007"
    assert result_map["tables"][0]["docling_table_ids"] == ["docling-table-0003"]
    assert result_map["docling_tables"][0]["normalized_csv"] == ("../../../docling/nap_table_1.csv")
    assert not (result_dir / "assets").exists()
