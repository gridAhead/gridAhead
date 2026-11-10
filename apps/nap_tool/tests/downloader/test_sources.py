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

GRAPHQL_URL = "https://example.test/graphql"
WSW = "wsw"


def _report(document_id, tag, version, uploaded, filename, kind="NETZAUSBAUPLAN"):
    return {
        "_id": document_id,
        "url": f"https://www.vnbdigital.de/gateway/files?serviceName=vnb&fileId={document_id}",
        "uploadDate": uploaded,
        "metadata": {
            "filename": filename,
            "title": f"Netzausbauplan_WSW_Netz_GmbH_{tag[-4:]}",
            "type": kind,
            "tag": tag,
            "version": version,
            "publicationAt": None,
        },
    }


# Trimmed from VNBdigital responses of 2026-11-10 (WSW Netz GmbH), provider ids replaced.
WSW_DOCUMENTS = [
    _report(
        "6aee326c8834460c54fece66",
        "Netzausbauplan_2026",
        "DRAFT",
        1793995320000,
        "WSW-Netz-S-178_Bericht_nach_14d_EnWG_202610.31_Rev1-0_Abgabe.pdf",
    ),
    # An XLSX slot uploaded after the report must not replace it.
    _report(
        "6aee3a1f8834460c54fece70",
        "Netzausbauplan_2026",
        "DRAFT",
        1794043800000,
        "WSW_Massnahmen_2026.xlsx",
        kind="NETZAUSBAUPLAN_MASSNAHMEN",
    ),
    _report(
        "66f1329dca60bbdfaa229f72",
        "Netzausbauplan_2024",
        "FINAL",
        1727083140000,
        "WSW-Netz-S-178_Bericht_nach_§14d_EnWG_20240917_Rev1-3.pdf",
    ),
]


def _portal(providers, documents):
    """Stand in for VNBdigital: the provider list, then the documents of one provider."""
    calls = []

    def request(_url, _query, variables=None):
        calls.append(variables)
        if variables is None:
            return {"data": {"vnb_vnbs": providers}}
        return {
            "data": {"vnb_gridExpansionDocumentsExternal": documents.get(variables["vnbId"], [])}
        }

    return request, calls


def _provider(provider_id, name, nap_active=True):
    return {
        "_id": provider_id,
        "name": name,
        "services": [{"type": {"type": "nap"}, "activated": nap_active}],
    }


def test_latest_vnbdigital_candidates_selects_the_newest_report(monkeypatch) -> None:
    """Each NAP provider yields its newest NAP report; XLSX slots and inactive providers don't."""
    providers = [
        _provider(WSW, "WSW Netz GmbH"),
        _provider("empty", "Gemeindewerke Wadgassen GmbH"),
        _provider("inactive", "Inactive Grid", nap_active=False),
    ]
    request, calls = _portal(providers, {WSW: WSW_DOCUMENTS})
    monkeypatch.setattr(sources, "_graphql_request", request)

    candidates = sources._latest_vnbdigital_candidates(GRAPHQL_URL)

    assert candidates == [
        {
            "provider_name": "WSW Netz GmbH",
            "provider_slug": "wsw-netz-gmbh",
            "source_provider_id": WSW,
            "document_id": "6aee326c8834460c54fece66",
            "document_name": "WSW-Netz-S-178_Bericht_nach_14d_EnWG_202610.31_Rev1-0_Abgabe.pdf",
            "source_url": "https://www.vnbdigital.de/gateway/files?serviceName=vnb"
            "&fileId=6aee326c8834460c54fece66&preview=1",
            "version": "2026-11-06T20:02:00+00:00",
            "nap_year": 2026,
        }
    ]
    assert calls == [None, {"vnbId": WSW}, {"vnbId": "empty"}]


def test_report_ranking_within_a_round(monkeypatch) -> None:
    """Within a round, a report marked invalid loses, then FINAL beats DRAFT despite age."""
    documents = [
        _report("draft", "Netzausbauplan_2024", "DRAFT", 1715007240000, "NAP_2024.pdf"),
        _report("final", "Netzausbauplan_2024", "FINAL", 1714485600000, "NAP_2024_final.pdf"),
        _report("invalid", "Netzausbauplan_2024", "FINAL", 1727769600000, "NAP_2024_ungültig.pdf"),
    ]
    request, _ = _portal([_provider(WSW, "WSW Netz GmbH")], {WSW: documents})
    monkeypatch.setattr(sources, "_graphql_request", request)

    [candidate] = sources._latest_vnbdigital_candidates(GRAPHQL_URL)

    assert candidate["document_id"] == "final"
    assert candidate["nap_year"] == 2024


def test_nap_providers_without_any_report_fail_loudly(monkeypatch) -> None:
    """Providers offering the NAP service but no report anywhere means the API changed."""
    request, _ = _portal([_provider(WSW, "WSW Netz GmbH")], {})
    monkeypatch.setattr(sources, "_graphql_request", request)

    with pytest.raises(RuntimeError, match="API may have changed"):
        sources._latest_vnbdigital_candidates(GRAPHQL_URL)


def test_graphql_errors_stop_discovery(monkeypatch) -> None:
    """An error in a per-provider document query is reported, not skipped."""

    def request(_url, _query, variables=None):
        if variables is None:
            return {"data": {"vnb_vnbs": [_provider(WSW, "WSW Netz GmbH")]}}
        return {"errors": [{"message": "Cannot query field"}]}

    monkeypatch.setattr(sources, "_graphql_request", request)

    with pytest.raises(RuntimeError, match="returned errors"):
        sources._latest_vnbdigital_candidates(GRAPHQL_URL)


def test_discover_vnbdigital_returns_candidates_without_downloading(monkeypatch) -> None:
    """Discovery returns metadata without reading a document URL."""
    candidate = {
        "provider_name": "Example Grid",
        "provider_slug": "example-grid",
        "source_provider_id": "provider-1",
        "document_id": "document-1",
        "document_name": "NAP 2025",
        "source_url": "https://example.test/nap.pdf",
        "version": None,
        "nap_year": 2025,
    }
    monkeypatch.setattr(sources, "_latest_vnbdigital_candidates", lambda _url: [candidate])
    monkeypatch.setattr(
        sources,
        "_read_url",
        lambda _url: (_ for _ in ()).throw(AssertionError("discovery downloaded a PDF")),
    )

    assert sources.discover_vnbdigital(VnbDigitalConfig()) == [candidate]


@pytest.mark.network
def test_live_portal_still_lists_nap_reports() -> None:
    """Calls the real VNBdigital portal (about 100 requests); run with `pytest -m network`."""
    candidates = sources.discover_vnbdigital(VnbDigitalConfig())

    assert candidates
    assert all(item["nap_year"] for item in candidates)
    assert all("fileId=" in item["source_url"] for item in candidates)


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
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
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
