# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""OSM grid objects: Overpass export, storage next to the place data (ADR-0008)."""

from __future__ import annotations

import csv
import http.client
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from nap_tool.downloader.sources import USER_AGENT, url_opener
from nap_tool.generations import csv_bytes

from .config import OsmSettings
from .objects import GridObject
from .place_data import PLACE_DATA_DIR
from .versioned_data import VersionedSource

SOURCE = "osm_objects"
OBJECT_FIELDS = ["id", "cls", "name", "operator", "ref", "voltage", "lat", "lon"]
MANIFEST_KEYS = (
    "source",
    "url",
    "sha256",
    "downloaded_at",
    "data_status",
    "classes",
    "objects_count",
    "unnamed_dropped",
    "objects_sha256",
    "attribution",
)
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)"
BUSY_CODES = {429, 502, 503, 504}
STORE = VersionedSource(
    directory=PLACE_DATA_DIR,
    name=SOURCE,
    label="OSM data",
    manifest_keys=MANIFEST_KEYS,
    classes_key="classes",
    source_file="source.json",
    lookup_file="objects.csv",
)


@dataclass(frozen=True)
class OsmData:
    """The current OSM data version with its manifest and objects."""

    version: str
    manifest: dict
    objects: list[GridObject]


@dataclass(frozen=True)
class OsmFetchResult:
    """Outcome of ``fetch``."""

    version: str
    changed: bool
    objects: int
    unnamed: int
    repaired: bool = False


def overpass_query(classes: list[str]) -> str:
    """Overpass QL for the named power objects of Germany.

    Args:
        classes: OSM ``power`` values to fetch.

    Returns:
        The query text; nodes, ways and relations come with a centre point.
    """
    pattern = "|".join(classes)
    return (
        '[out:json][timeout:240];area["ISO3166-1"="DE"][admin_level=2]->.de;'
        f'nwr["power"~"^({pattern})$"](area.de);out center tags;'
    )


def _send(request: urllib.request.Request) -> bytes:
    with url_opener().open(request, timeout=300) as response:
        return response.read()


def post_query(
    url: str,
    query: str,
    *,
    send: Callable[[urllib.request.Request], bytes] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> bytes:
    """Run an Overpass query, retrying a busy server with exponential backoff.

    Args:
        url: Overpass endpoint.
        query: Overpass QL.
        send: Sends a request and returns the body; the default uses HTTP.
        sleep: Pause function (30 s, then 60 s, ...).
        attempts: Tries before giving up (at least 1).

    Only busy HTTP codes are retried; timeouts and connection errors are not, so a failed
    run can simply be rerun by hand.

    Returns:
        The response body.

    Raises:
        ValueError: If ``attempts`` is below 1.
        RuntimeError: If the server stays busy, refuses the query, or cannot be reached.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    delay = 30.0
    for attempt in range(1, attempts + 1):
        try:
            return (send or _send)(request)
        except urllib.error.HTTPError as error:
            if error.code in BUSY_CODES and attempt < attempts:
                sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"Overpass server {url} answered {error.code}") from error
        except (OSError, http.client.HTTPException) as error:
            raise RuntimeError(f"Failed to query Overpass server {url}: {error}") from error
    raise AssertionError("unreachable: every attempt returns or raises")


def parse_objects(content: bytes, classes: list[str]) -> tuple[list[GridObject], int, str]:
    """Named objects of an Overpass JSON answer.

    Args:
        content: Response body.
        classes: OSM ``power`` values to keep.

    Returns:
        Objects sorted by id, the number of unnamed objects skipped, and the data status
        (OSM base timestamp, '' if absent).

    Raises:
        ValueError: If the body is not Overpass JSON, carries an Overpass ``remark`` (timeout,
            out of memory: the export may be truncated), or an element is invalid or has bad
            coordinates.

    Elements of a wanted class with a name but without a position are skipped.
    """
    try:
        data = json.loads(content)
    except ValueError as error:
        raise ValueError("OSM download is not valid JSON") from error
    if not isinstance(data, dict) or "elements" not in data:
        raise ValueError("OSM answer has no elements")
    remark = data.get("remark")
    if isinstance(remark, str) and remark.strip():
        raise ValueError(f"Overpass reported: {remark}")
    status = str((data.get("osm3s") or {}).get("timestamp_osm_base", ""))
    objects, unnamed = [], 0
    for element in data["elements"]:
        if not isinstance(element, dict):
            raise ValueError(f"OSM answer has an invalid element: {element!r}")
        tags = element.get("tags") or {}
        if tags.get("power") not in classes:
            continue
        name = (tags.get("name") or "").strip()
        if not name:
            unnamed += 1
            continue
        point = element if "lat" in element else element.get("center")
        if not point:
            continue
        label = f"{element.get('type')}/{element.get('id')}"
        try:
            lat, lon = float(point["lat"]), float(point["lon"])
            if not (math.isfinite(lat) and math.isfinite(lon)):
                raise ValueError("coordinates are not finite")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"OSM element {label}: {error}") from error
        objects.append(
            GridObject(
                id=label,
                cls=tags["power"],
                name=name,
                operator=tags.get("operator", ""),
                ref=tags.get("ref", ""),
                voltage=tags.get("voltage", ""),
                lat=round(lat, 6),
                lon=round(lon, 6),
            )
        )
    objects.sort(key=lambda item: item.id)
    return objects, unnamed, status


def objects_bytes(objects: list[GridObject]) -> bytes:
    """The prepared lookup as CSV (``OBJECT_FIELDS`` header, coordinates with six decimals)."""
    rows = [
        {
            "id": item.id,
            "cls": item.cls,
            "name": item.name,
            "operator": item.operator,
            "ref": item.ref,
            "voltage": item.voltage,
            "lat": f"{item.lat:.6f}",
            "lon": f"{item.lon:.6f}",
        }
        for item in objects
    ]
    return csv_bytes(rows, OBJECT_FIELDS)


def _read_objects_csv(path: Path) -> list[GridObject]:
    with path.open(encoding="utf-8", newline="") as source:
        return [
            GridObject(
                id=row["id"],
                cls=row["cls"],
                name=row["name"],
                operator=row["operator"],
                ref=row["ref"],
                voltage=row["voltage"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
            )
            for row in csv.DictReader(source)
        ]


def current_version(root: Path) -> str | None:
    """Version of the OSM data pointer, or None without OSM data.

    Args:
        root: Data repository root.

    Returns:
        The 8-hex-digit version, or None if there is no pointer.

    Raises:
        ValueError: If the pointer is malformed.
    """
    return STORE.current_version(root)


def load(root: Path, *, with_objects: bool = True) -> OsmData | None:
    """Load the current OSM data after checking its hash.

    Args:
        root: Data repository root.
        with_objects: Parse ``objects.csv``; otherwise ``objects`` is empty. The hash and
            the manifest are verified either way.

    Returns:
        The data, or None when there is no OSM data (it is optional).

    Raises:
        ValueError: If the pointer is malformed.
        RuntimeError: If the manifest is unusable or ``objects.csv`` is missing or modified.
    """
    loaded = STORE.load_current(root)
    if loaded is None:
        return None
    version, manifest, path = loaded
    return OsmData(version, manifest, _read_objects_csv(path) if with_objects else [])


def fetch(
    root: Path,
    settings: OsmSettings,
    *,
    force: bool = False,
    content: bytes | None = None,
    post: Callable[[str, str], bytes] | None = None,
) -> OsmFetchResult:
    """Store an Overpass export as the current OSM data.

    The current version is kept if the export, its files and the classes are unchanged; a
    malformed pointer is overwritten.

    Args:
        root: Data repository root.
        settings: Overpass URL and classes.
        force: Rebuild even if the export equals the current version.
        content: A saved export to import; otherwise Overpass is queried.
        post: Query function ``(url, query) -> bytes``; defaults to ``post_query``.

    Returns:
        Version (first 8 hex digits of the export's SHA-256), whether it changed, object and
        skipped-unnamed counts, and whether a damaged current version was rebuilt.

    Raises:
        RuntimeError: If Overpass cannot be queried.
        ValueError: If the export is not Overpass JSON or holds no named objects.
        OSError: If the version cannot be written.
    """
    if content is None:
        content = (post or post_query)(settings.overpass_url, overpass_query(settings.classes))

    def build(export: bytes) -> tuple[bytes, dict]:
        objects, unnamed, data_status = parse_objects(export, settings.classes)
        if not objects:
            raise ValueError("OSM export has no named objects of the configured classes")
        return objects_bytes(objects), {
            "source": "OpenStreetMap via Overpass",
            "url": settings.overpass_url,
            "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "data_status": data_status,
            "classes": settings.classes,
            "objects_count": len(objects),
            "unnamed_dropped": unnamed,
            "attribution": ATTRIBUTION,
        }

    classes = None if force else settings.classes
    stored = STORE.store(root, content, classes=classes, build=build)
    manifest = stored.manifest
    return OsmFetchResult(
        stored.version,
        stored.changed,
        manifest["objects_count"],
        manifest["unnamed_dropped"],
        stored.repaired,
    )
