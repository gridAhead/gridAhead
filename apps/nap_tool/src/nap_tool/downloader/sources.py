# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Source-specific download logic for NAP documents."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TypedDict
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from nap_tool.config import HubConfig, Provider, SourceType, VnbDigitalConfig

USER_AGENT = "nap-tool/0.1 (+https://github.com/rl-institut/nap_tool)"


class NAPCandidate(TypedDict):
    """A downloadable NAP document discovered in VNBdigital."""

    provider_name: str
    provider_slug: str
    source_provider_id: str
    document_id: str
    document_name: str
    source_url: str
    version: str | None
    nap_year: int | None


class _LinkParser(HTMLParser):
    """Collect links and their visible labels from a small HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def download_provider(provider: Provider, hub: HubConfig | None, raw_dir: Path) -> bool:
    """Fetch one configured provider into ``data/raw/<slug>``.

    Args:
        provider: Provider registry entry to download.
        hub: Optional shared hub-page configuration for ``hub`` sources.
        raw_dir: Base raw-data directory.

    Raises:
        ValueError: If required source configuration is missing.

    Returns:
        Whether a document was downloaded and should enter the current run.
    """
    if provider.source_type == SourceType.MANUAL:
        print(f"[{provider.slug}] skipped: manual PDF import is not supported")
        return False
    provider_dir = raw_dir / provider.slug
    provider_dir.mkdir(parents=True, exist_ok=True)

    if provider.source_type == SourceType.HUB:
        if hub is None:
            raise ValueError(f"[{provider.slug}] hub source requires a top-level hub.url")
        _download_from_hub(provider, hub, provider_dir)
        return True
    elif provider.source_type == SourceType.CUSTOM:
        _download_from_url(provider, provider_dir)
        return True
    elif provider.source_type == SourceType.VNBDIGITAL:
        raise ValueError("Use the top-level vnbdigital configuration instead of a provider entry.")
    raise ValueError(f"Unsupported source type: {provider.source_type}")


def discover_vnbdigital(
    config: VnbDigitalConfig, provider_slug: str | None = None
) -> list[NAPCandidate]:
    """Discover each provider's newest NAP from VNBdigital.

    Args:
        config: VNBdigital endpoint configuration.
        provider_slug: Optional slug used to limit discovery.

    Returns:
        Latest discovered candidates.

    Raises:
        ValueError: If the requested provider is not returned by VNBdigital.
    """
    candidates = _latest_vnbdigital_candidates(config.graphql_url)
    if provider_slug is not None:
        candidates = [item for item in candidates if item["provider_slug"] == provider_slug]
        if not candidates:
            raise ValueError(f"No VNBdigital provider matches slug {provider_slug!r}.")
    return candidates


def download_vnbdigital_pdf(source_url: str) -> bytes:
    """Download and validate one VNBdigital PDF without changing local state.

    Args:
        source_url: Direct VNBdigital document URL.

    Returns:
        Downloaded PDF bytes.

    Raises:
        RuntimeError: If the request fails or does not return a PDF.
    """

    try:
        data = read_url(source_url)
    except OSError as exc:
        raise RuntimeError(f"Failed to download PDF: {exc.__class__.__name__}") from exc
    if not data:
        raise RuntimeError("Downloaded an empty PDF")
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Expected a PDF but received a different response")
    return data


def discover_configured(provider: Provider, hub: HubConfig | None) -> list[tuple[str, str]]:
    """Discover URLs and titles for one configured provider.

    Args:
        provider: Provider registry entry.
        hub: Shared hub configuration when needed.

    Returns:
        Pairs of document title and URL.

    Raises:
        ValueError: If source configuration is incomplete.
    """
    if provider.source_type == SourceType.MANUAL:
        return []
    if provider.source_type == SourceType.CUSTOM:
        if provider.url is None:
            raise ValueError(f"[{provider.slug}] custom source requires url")
        return [(_filename_from_url(provider.url), provider.url)]
    if provider.source_type == SourceType.HUB:
        if hub is None or provider.hub_match is None:
            raise ValueError(f"[{provider.slug}] hub source requires hub.url and hub_match")
        parser = _LinkParser()
        parser.feed(read_url(hub.url).decode("utf-8", errors="replace"))
        return [
            (label or _filename_from_url(urljoin(hub.url, href)), urljoin(hub.url, href))
            for href, label in parser.links
            if provider.hub_match.casefold() in label.casefold()
        ]
    raise ValueError(f"Unsupported configured source type: {provider.source_type}")


def _download_from_hub(provider: Provider, hub: HubConfig, provider_dir: Path) -> None:
    """Find labelled links on a shared hub page and download matching files."""
    if not provider.hub_match:
        raise ValueError(f"[{provider.slug}] hub source requires hub_match")
    page = read_url(hub.url).decode("utf-8", errors="replace")
    parser = _LinkParser()
    parser.feed(page)
    matching_urls = [
        urljoin(hub.url, href)
        for href, label in parser.links
        if provider.hub_match.casefold() in label.casefold()
    ]
    if not matching_urls:
        raise ValueError(f"[{provider.slug}] no hub links match {provider.hub_match!r}")
    # Hub pages are third-party content: never let them point at file:// or other schemes.
    if any(urlparse(url).scheme not in {"http", "https"} for url in matching_urls):
        raise ValueError(f"[{provider.slug}] hub page links to a non-HTTP URL")
    filenames = [_filename_from_url(url) for url in matching_urls]
    files = [
        _download_document(url, provider_dir / name)
        for url, name in zip(matching_urls, filenames, strict=True)
    ]
    _write_metadata(provider_dir, _configured_metadata(provider, files, matching_urls, filenames))
    print(f"[{provider.slug}] downloaded {len(files)} file(s)")


def _download_from_url(provider: Provider, provider_dir: Path) -> None:
    """Download a configured direct URL into the provider's raw directory."""
    if not provider.url:
        raise ValueError(f"[{provider.slug}] custom source requires url")
    filename = _filename_from_url(provider.url)
    metadata = _download_document(provider.url, provider_dir / filename)
    _write_metadata(
        provider_dir, _configured_metadata(provider, [metadata], [provider.url], [filename])
    )
    print(f"[{provider.slug}] downloaded {filename}")


def _configured_metadata(
    provider: Provider,
    files: list[dict[str, str | int]],
    urls: list[str],
    names: list[str],
) -> dict[str, object]:
    return {
        "provider": provider.name,
        "provider_slug": provider.slug,
        "source_type": provider.source_type.value,
        "downloaded_at": _timestamp(),
        "files": [
            {"path": name, "source_url": url, **metadata}
            for name, url, metadata in zip(names, urls, files, strict=True)
        ],
    }


# VNBdigital's own frontend loads grid expansion documents per provider with
# vnb_gridExpansionDocumentsExternal; the `documents` field of vnb_vnbs no longer holds them.
_PROVIDERS_QUERY = """
query {
  vnb_vnbs { _id name services { type { type } activated } }
}
"""
_DOCUMENTS_QUERY = """
query ($vnbId: ID!) {
  vnb_gridExpansionDocumentsExternal(vnbId: $vnbId) {
    _id url uploadDate
    metadata { filename title type tag version publicationAt }
  }
}
"""
# Upload slot of the NAP report (PDF); the other slots are XLSX measure lists.
NAP_REPORT_TYPE = "NETZAUSBAUPLAN"


def _latest_vnbdigital_candidates(graphql_url: str) -> list[NAPCandidate]:
    """Query VNBdigital and select the newest NAP report of every NAP provider.

    Raises:
        RuntimeError: If a request fails, or if providers offer the NAP service but
            none of them has a NAP report, which means the API changed.
    """
    providers = _graphql_data(graphql_url, _PROVIDERS_QUERY).get("vnb_vnbs")
    if not isinstance(providers, list):
        raise RuntimeError("VNBdigital GraphQL response has no vnb_vnbs list")
    active = [item for item in providers if isinstance(item, dict) and _nap_service_active(item)]

    candidates: list[NAPCandidate] = []
    for provider in active:
        provider_name = str(provider.get("name") or "")
        provider_id = str(provider.get("_id") or "")
        if not provider_name or not provider_id:
            continue
        documents = _graphql_data(graphql_url, _DOCUMENTS_QUERY, {"vnbId": provider_id}).get(
            "vnb_gridExpansionDocumentsExternal"
        )
        reports = [item for item in documents or [] if _is_nap_report(item)]
        if not reports:
            continue
        newest = max(reports, key=_report_score)
        metadata = newest["metadata"]
        published = metadata.get("publicationAt") or newest.get("uploadDate")
        candidates.append(
            {
                "provider_name": provider_name,
                "provider_slug": _provider_slug(provider_name),
                "source_provider_id": provider_id,
                "document_id": newest["_id"],
                "document_name": str(metadata.get("filename") or metadata.get("title") or "NAP"),
                "source_url": _with_preview(newest["url"]),
                "version": _iso_timestamp(published) if isinstance(published, int) else None,
                "nap_year": _nap_year(metadata),
            }
        )
    if active and not candidates:
        raise RuntimeError(
            f"VNBdigital lists {len(active)} providers with the NAP service but no NAP "
            "report; its API may have changed"
        )
    return sorted(candidates, key=lambda item: item["provider_slug"])


def _graphql_data(
    graphql_url: str, query: str, variables: dict[str, object] | None = None
) -> dict[str, object]:
    payload = _graphql_request(graphql_url, query, variables)
    if payload.get("errors"):
        raise RuntimeError(f"VNBdigital GraphQL returned errors: {payload['errors']}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("VNBdigital GraphQL response has no data")
    return data


def _graphql_request(
    graphql_url: str, query: str, variables: dict[str, object] | None = None
) -> dict[str, object]:
    request = Request(
        graphql_url,
        data=json.dumps({"query": query, "variables": variables or {}}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with url_opener().open(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"VNBdigital GraphQL request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("VNBdigital GraphQL response is not an object")
    return result


def _nap_service_active(provider: dict[str, object]) -> bool:
    services = provider.get("services")
    if not isinstance(services, list):
        return False
    return any(
        isinstance(service, dict)
        and service.get("activated") is True
        and isinstance(service.get("type"), dict)
        and service["type"].get("type") == "nap"
        for service in services
    )


def _is_nap_report(document: object) -> bool:
    return (
        isinstance(document, dict)
        and isinstance(document.get("_id"), str)
        and isinstance(document.get("url"), str)
        and bool(document["url"])
        and isinstance(document.get("metadata"), dict)
        and document["metadata"].get("type") == NAP_REPORT_TYPE
    )


def _report_score(document: dict[str, object]) -> tuple[int, bool, bool, int]:
    """Rank reports: newest round, then not marked invalid, then FINAL, then newest upload."""
    metadata = document["metadata"]
    name = f"{metadata.get('filename') or ''} {metadata.get('title') or ''}".casefold()
    valid = not any(marker in name for marker in ("ungültig", "ungueltig"))
    uploaded = document.get("uploadDate")
    return (
        _nap_year(metadata) or 0,
        valid,
        metadata.get("version") == "FINAL",
        uploaded if isinstance(uploaded, int) else 0,
    )


def _nap_year(metadata: dict[str, object]) -> int | None:
    """Read the NAP round from a tag such as `Netzausbauplan_2026`."""
    match = re.fullmatch(r"Netzausbauplan_(20\d{2})", str(metadata.get("tag") or ""))
    return int(match.group(1)) if match else None


def _iso_timestamp(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat()


def _with_preview(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("serviceName", "vnb")
    query["preview"] = "1"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _provider_slug(name: str) -> str:
    normalized = (
        name.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    normalized = re.sub(r"\(.*?\)", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "unknown-provider"


def read_url(url: str) -> bytes:
    """Download a URL with the tool's user agent, bypassing proxy variables.

    Args:
        url: URL to read.

    Returns:
        The response body.

    Raises:
        OSError: If the request fails (URLError and HTTPError included).
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with url_opener().open(request, timeout=90) as response:
        return response.read()


def url_opener() -> OpenerDirector:
    """Return an opener that connects directly instead of inheriting proxy variables.

    Returns:
        A urllib opener without proxy handling.
    """
    return build_opener(ProxyHandler({}))


def _download_document(source_url: str, output_path: Path) -> dict[str, str | int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.part")
    try:
        data = read_url(source_url)
    except OSError as exc:
        raise RuntimeError(f"Failed to download {source_url}: {exc}") from exc
    if not data:
        raise RuntimeError(f"Downloaded an empty file from {source_url}")
    if output_path.suffix.casefold() == ".pdf" and not data.startswith(b"%PDF"):
        raise RuntimeError(f"Expected a PDF from {source_url}, but received a different response")
    with temporary_path.open("wb") as output_file:
        output_file.write(data)
    temporary_path.replace(output_path)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _filename_from_url(url: str) -> str:
    filename = Path(urlparse(url).path).name
    if not filename or filename in {"files", "download"}:
        filename = "document.pdf"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip(".-")
    return sanitized or "document.pdf"


def _write_metadata(provider_dir: Path, metadata: dict[str, object]) -> None:
    with (provider_dir / "metadata.json").open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)
        metadata_file.write("\n")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
