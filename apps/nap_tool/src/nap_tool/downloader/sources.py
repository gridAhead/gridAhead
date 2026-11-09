# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
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
from urllib.request import ProxyHandler, Request, build_opener

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
    current_from: int | None
    current_to: int | None


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
        data = _read_url(source_url)
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
        parser.feed(_read_url(hub.url).decode("utf-8", errors="replace"))
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
    page = _read_url(hub.url).decode("utf-8", errors="replace")
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


def _latest_vnbdigital_candidates(graphql_url: str) -> list[NAPCandidate]:
    """Query VNBdigital and select its newest likely NAP per provider."""
    payload = _graphql_request(graphql_url)
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"VNBdigital GraphQL returned errors: {errors}")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("vnb_vnbs"), list):
        raise RuntimeError("VNBdigital GraphQL response has no vnb_vnbs list")

    candidates: list[NAPCandidate] = []
    for provider in data["vnb_vnbs"]:
        if not isinstance(provider, dict) or not _nap_service_active(provider):
            continue
        provider_name = str(provider.get("name") or "")
        provider_id = str(provider.get("_id") or "")
        if not provider_name or not provider_id:
            continue
        documents = _nap_documents(provider)
        if not documents:
            continue
        newest = max(documents, key=_document_score)
        source_url = str(newest.get("url") or "")
        if not source_url:
            continue
        current_from = newest.get("currentFrom")
        current_to = newest.get("currentTo")
        candidates.append(
            {
                "provider_name": provider_name,
                "provider_slug": _provider_slug(provider_name),
                "source_provider_id": provider_id,
                "document_id": str(newest.get("_id") or provider_id),
                "document_name": str(newest.get("name") or newest.get("title") or "NAP"),
                "source_url": _with_preview(source_url),
                "current_from": current_from if isinstance(current_from, int) else None,
                "current_to": current_to if isinstance(current_to, int) else None,
            }
        )
    return sorted(candidates, key=lambda item: item["provider_slug"])


def _graphql_request(graphql_url: str) -> dict[str, object]:
    query = """
    query {
      vnb_vnbs {
        _id name
        services { type { type } activated }
        documents {
          _id name title category url currentFrom currentTo
          attachments { _id name title category url }
        }
      }
    }
    """
    request = Request(
        graphql_url,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with _url_opener().open(request, timeout=90) as response:
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


def _nap_documents(provider: dict[str, object]) -> list[dict[str, object]]:
    documents = provider.get("documents")
    if not isinstance(documents, list):
        return []
    candidates: list[dict[str, object]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        if _looks_like_nap(document):
            candidates.append(document)
        attachments = document.get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if isinstance(attachment, dict) and _looks_like_nap(attachment):
                    candidates.append(
                        {
                            **attachment,
                            "currentFrom": document.get("currentFrom"),
                            "currentTo": document.get("currentTo"),
                        }
                    )
    return [candidate for candidate in candidates if candidate.get("url")]


def _looks_like_nap(document: dict[str, object]) -> bool:
    text = " ".join(
        str(document.get(key) or "") for key in ("name", "title", "category", "url")
    ).casefold()
    return any(
        marker in text
        for marker in ("netzausbau", "netzausbauplan", "netzausbaubericht", "14d", "nap")
    )


def _document_score(document: dict[str, object]) -> tuple[int, int, str]:
    name = str(document.get("name") or document.get("title") or "").casefold()
    current_from = document.get("currentFrom")
    timestamp = current_from if isinstance(current_from, int) else 0
    preference = 0
    for marker, points in (
        ("aktualisiert", 90),
        ("angepasst", 80),
        ("aktuell", 40),
        ("final", 20),
        ("erstfassung", -15),
        ("anlage", -90),
        ("netzkarte", -120),
        ("ungueltig", -1000),
        ("ungültig", -1000),
    ):
        if marker in name:
            preference += points
    return timestamp, preference, name


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


def _read_url(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with _url_opener().open(request, timeout=90) as response:
        return response.read()


def _url_opener():
    """Return an opener that connects directly instead of inheriting proxy variables."""
    return build_opener(ProxyHandler({}))


def _download_document(source_url: str, output_path: Path) -> dict[str, str | int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.part")
    try:
        data = _read_url(source_url)
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
