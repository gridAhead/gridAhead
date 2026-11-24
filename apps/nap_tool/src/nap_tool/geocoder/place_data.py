# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Offline place data: download BKG GN250, keep settlement points, load them (ADR-0007)."""

from __future__ import annotations

import csv
import http.client
import io
import math
import subprocess
import zipfile
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from nap_tool.downloader.sources import read_url
from nap_tool.generations import csv_bytes

from .config import PlaceDataSettings
from .match import Place
from .utm import utm32_to_wgs84
from .versioned_data import VersionedSource

PLACE_DATA_DIR = "place_data"
SOURCE = "gn250"
PLACES_FIELDS = ["id", "name", "name2", "object_class", "ags", "lat", "lon", "population"]
REQUIRED_COLUMNS = ("NNID", "OBA", "NAME", "NAME2", "AGS", "EWZ", "EWZ_GER", "RECHTS", "HOCH")
DATA_STATUS_MEMBER = "dokumentation/aktualitaet.txt"
DATA_SOURCES_URL = (
    "https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_gn250.pdf"
)
MANIFEST_KEYS = (
    "source",
    "url",
    "sha256",
    "downloaded_at",
    "data_status",
    "object_classes",
    "places_count",
    "places_sha256",
    "attribution",
)
STORE = VersionedSource(
    directory=PLACE_DATA_DIR,
    name=SOURCE,
    label="place data",
    manifest_keys=MANIFEST_KEYS,
    classes_key="object_classes",
    source_file="source.zip",
    lookup_file="places.csv",
)


@dataclass(frozen=True)
class PlaceData:
    """The current place data version with its manifest and places."""

    version: str
    manifest: dict
    places: list[Place]


@dataclass(frozen=True)
class FetchResult:
    """Outcome of ``fetch``."""

    version: str
    changed: bool
    places: int
    repaired: bool = False


def _read_places(reader: csv.DictReader, settings: PlaceDataSettings) -> list[Place]:
    """Settlement rows of an open GN250 CSV, converted to WGS84."""
    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"GN250 CSV lacks columns: {', '.join(missing)}")
    places = []
    for record in reader:
        if record["OBA"] not in settings.object_classes:
            continue
        try:
            easting, northing = float(record["RECHTS"]), float(record["HOCH"])
            if not (math.isfinite(easting) and math.isfinite(northing)):
                raise ValueError("coordinates are not finite")
            lat, lon = utm32_to_wgs84(easting, northing)
            places.append(
                Place(
                    id=record["NNID"],
                    name=record["NAME"],
                    name2=record["NAME2"],
                    object_class=record["OBA"],
                    ags=record["AGS"],
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    population=int(record["EWZ"] or record["EWZ_GER"] or 0),
                )
            )
        except (ValueError, TypeError) as error:
            line = f"GN250 line {reader.line_num} ({record.get('NNID', '')}): {error}"
            raise ValueError(line) from error
    return places


def parse_places(content: bytes, settings: PlaceDataSettings) -> tuple[list[Place], str]:
    """Settlement points of a GN250 CSV ZIP.

    Args:
        content: The downloaded ZIP.
        settings: CSV member and object classes to keep.

    Returns:
        Kept places with WGS84 coordinates, and the data status ('' if absent).

    Raises:
        ValueError: If the download is not a valid ZIP archive, the CSV member or required
            columns are missing, or a row is malformed.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = set(archive.namelist())
            if settings.member not in members:
                raise ValueError(f"GN250 archive lacks {settings.member}")
            status = ""
            if DATA_STATUS_MEMBER in members:
                status = archive.read(DATA_STATUS_MEMBER).decode("utf-8-sig").strip()
            with io.TextIOWrapper(
                archive.open(settings.member), encoding="utf-8-sig", newline=""
            ) as text:
                places = _read_places(csv.DictReader(text, delimiter=";"), settings)
    except (zipfile.BadZipFile, zlib.error, EOFError) as error:
        raise ValueError("GN250 download is not a valid ZIP archive") from error
    return places, status


def places_bytes(places: list[Place]) -> bytes:
    """The prepared lookup as CSV.

    Args:
        places: Places to write, in order.

    Returns:
        UTF-8 CSV bytes with ``PLACES_FIELDS`` as header.
    """
    rows = [
        {
            "id": place.id,
            "name": place.name,
            "name2": place.name2,
            "object_class": place.object_class,
            "ags": place.ags,
            "lat": f"{place.lat:.6f}",
            "lon": f"{place.lon:.6f}",
            "population": place.population,
        }
        for place in places
    ]
    return csv_bytes(rows, PLACES_FIELDS)


def current_version(root: Path) -> str | None:
    """Version the place data pointer names, or None without place data.

    Args:
        root: Data repository root.

    Returns:
        The 8-hex-digit version, or None if there is no pointer.

    Raises:
        ValueError: If the pointer is malformed.
    """
    return STORE.current_version(root)


def fetch(
    root: Path,
    settings: PlaceDataSettings,
    *,
    force: bool = False,
    read: Callable[[str], bytes] | None = None,
) -> FetchResult:
    """Download GN250, build the lookup and make it the current version.

    The current version is kept if the download, its files and the object classes are
    unchanged; a malformed pointer is overwritten.

    Args:
        root: Data repository root.
        settings: Source URL, CSV member and object classes.
        force: Rebuild even if the download equals the current version.
        read: URL reader; the default downloads over HTTP.

    Returns:
        Version (first 8 hex digits of the ZIP's SHA-256), whether it changed, place count
        and whether a damaged current version was rebuilt.

    Raises:
        RuntimeError: If the download fails.
        ValueError: If the archive has an unexpected format or no places.
        OSError: If the version directory cannot be written (PermissionError included).
    """
    try:
        content = (read or read_url)(settings.url)
    except (OSError, http.client.HTTPException) as error:
        raise RuntimeError(f"Failed to download {settings.url}: {error}") from error

    def build(download: bytes) -> tuple[bytes, dict]:
        places, data_status = parse_places(download, settings)
        if not places:
            raise ValueError("GN250 archive has no places of the configured object classes")
        now = datetime.now(UTC)
        return places_bytes(places), {
            "source": "BKG GN250",
            "url": settings.url,
            "downloaded_at": now.isoformat(timespec="seconds"),
            "data_status": data_status,
            "object_classes": settings.object_classes,
            "places_count": len(places),
            "attribution": (
                f"© BKG ({now.year}) dl-de/by-2-0, Datenquellen: {DATA_SOURCES_URL}; "
                "Daten verändert: Auswahl der Gemeinden und Ortslagen, "
                "Koordinaten von UTM32 nach WGS84 umgerechnet"
            ),
        }

    classes = None if force else settings.object_classes
    stored = STORE.store(root, content, classes=classes, build=build)
    return FetchResult(
        stored.version, stored.changed, stored.manifest["places_count"], stored.repaired
    )


def _read_places_csv(path: Path) -> list[Place]:
    """Places of a prepared lookup CSV."""
    with path.open(encoding="utf-8", newline="") as source:
        return [
            Place(
                id=row["id"],
                name=row["name"],
                name2=row["name2"],
                object_class=row["object_class"],
                ags=row["ags"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                population=int(row["population"]),
            )
            for row in csv.DictReader(source)
        ]


def load(root: Path, *, with_places: bool = True) -> PlaceData:
    """Load the current place data after checking its hash.

    Args:
        root: Data repository root.
        with_places: Parse ``places.csv``; otherwise ``places`` is an empty list. The file's
            hash and the manifest are verified either way.

    Returns:
        Version, manifest and places.

    Raises:
        ValueError: If there is no place data or its pointer is malformed.
        RuntimeError: If the manifest is unusable or ``places.csv`` is missing or modified.
    """
    loaded = STORE.load_current(root)
    if loaded is None:
        raise ValueError("No place data; run `nap-tool place-data fetch`")
    version, manifest, path = loaded
    return PlaceData(version, manifest, _read_places_csv(path) if with_places else [])


def is_ignored(root: Path) -> bool | None:
    """Tell whether git ignores the place data folder of the data repository.

    Args:
        root: Data repository root.

    Returns:
        True or False; None when root is not a git repository or git is missing.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", f"{PLACE_DATA_DIR}/"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    return {0: True, 1: False}.get(result.returncode)
