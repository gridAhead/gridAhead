# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for source discovery and raw-download persistence."""

import json
from pathlib import Path

import pytest

from nap_tool.config import HubConfig, Provider, SourceType, VnbDigitalConfig
from nap_tool.downloader import sources


def test_latest_vnbdigital_candidates_selects_the_current_document(monkeypatch) -> None:
    """The most recent plan is selected for every active VNBdigital provider."""
    payload = {
        "data": {
            "vnb_vnbs": [
                {
                    "_id": "provider-1",
                    "name": "Müller Netz GmbH",
                    "services": [{"type": {"type": "nap"}, "activated": True}],
                    "documents": [
                        {
                            "_id": "old",
                            "name": "Netzausbauplan 2024",
                            "url": "https://example.test/files?fileId=old",
                            "currentFrom": 1,
                            "attachments": [],
                        },
                        {
                            "_id": "new",
                            "name": "Netzausbauplan 2025 aktualisiert",
                            "url": "https://example.test/files?fileId=new",
                            "currentFrom": 2,
                            "attachments": [],
                        },
                    ],
                },
                {
                    "_id": "inactive",
                    "name": "Inactive Grid",
                    "services": [{"type": {"type": "nap"}, "activated": False}],
                    "documents": [],
                },
            ]
        }
    }
    monkeypatch.setattr(sources, "_graphql_request", lambda _url: payload)

    candidates = sources._latest_vnbdigital_candidates("https://example.test/graphql")

    assert candidates == [
        {
            "provider_name": "Müller Netz GmbH",
            "provider_slug": "mueller-netz-gmbh",
            "source_provider_id": "provider-1",
            "document_id": "new",
            "document_name": "Netzausbauplan 2025 aktualisiert",
            "source_url": "https://example.test/files?fileId=new&serviceName=vnb&preview=1",
            "current_from": 2,
            "current_to": None,
        }
    ]


def test_discover_vnbdigital_returns_candidates_without_downloading(monkeypatch) -> None:
    """Discovery returns metadata without reading a document URL."""
    candidate = {
        "provider_name": "Example Grid",
        "provider_slug": "example-grid",
        "source_provider_id": "provider-1",
        "document_id": "document-1",
        "document_name": "NAP 2025",
        "source_url": "https://example.test/nap.pdf",
        "current_from": 123,
        "current_to": None,
    }
    monkeypatch.setattr(sources, "_latest_vnbdigital_candidates", lambda _url: [candidate])
    monkeypatch.setattr(
        sources,
        "_read_url",
        lambda _url: (_ for _ in ()).throw(AssertionError("discovery downloaded a PDF")),
    )

    assert sources.discover_vnbdigital(VnbDigitalConfig()) == [candidate]


def test_download_vnbdigital_pdf_validates_bytes(monkeypatch) -> None:
    """Downloading a candidate returns validated bytes without writing files."""

    monkeypatch.setattr(sources, "_read_url", lambda _url: b"%PDF-1.7")

    assert sources.download_vnbdigital_pdf("https://example.test/nap.pdf") == b"%PDF-1.7"


def test_direct_url_download_writes_metadata(tmp_path: Path) -> None:
    """A provider-specific URL remains available for future exceptional sources."""
    source_file = tmp_path / "source.pdf"
    source_file.write_bytes(b"%PDF-1.7")
    provider = Provider(
        name="Custom Grid",
        slug="custom-grid",
        source_type=SourceType.CUSTOM,
        url=source_file.as_uri(),
    )

    sources.download_provider(provider, None, tmp_path / "raw")

    metadata_path = tmp_path / "raw" / "custom-grid" / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    assert (tmp_path / "raw" / "custom-grid" / "source.pdf").is_file()
    assert metadata["files"][0]["path"] == "source.pdf"


def test_hub_download_rejects_non_http_links(monkeypatch, tmp_path: Path) -> None:
    """A hub page cannot make the downloader copy local files via file:// links."""
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.7 secret")
    page = f'<a href="{secret.as_uri()}">Custom Grid</a>'.encode()
    monkeypatch.setattr(
        sources, "_read_url", lambda url: page if url.startswith("https") else secret.read_bytes()
    )
    provider = Provider(
        name="Custom Grid",
        slug="custom-grid",
        source_type=SourceType.HUB,
        hub_match="Custom Grid",
    )

    with pytest.raises(ValueError, match="non-HTTP"):
        sources.download_provider(provider, HubConfig(url="https://hub.test/"), tmp_path / "raw")

    assert not (tmp_path / "raw" / "custom-grid" / "secret.pdf").exists()
