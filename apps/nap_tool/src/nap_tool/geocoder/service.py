# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Geocode the current classification output of a set and publish it as a generation."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from nap_tool.classifier import service as classification
from nap_tool.data import checked_file, resolve_path
from nap_tool.generations import (
    csv_bytes,
    json_bytes,
    publish_generation,
    published_directory,
    scheme_lock,
)

from .config import CONFIG_PATH, load_config
from .match import Matcher
from .objects import ObjectMatcher
from .osm_data import load as load_osm
from .place_data import load as load_place_data
from .records import GEOCODE_FIELDS, UNRESOLVED_FIELDS, GeocodeResult, geocode_rows
from .report import markdown_report

OUTPUT_FILES = (
    "geocoded.csv",
    "geocoded.geojson",
    "geocode_report.md",
    "geocode_report.json",
    "unresolved_names.csv",
)


def inputs(
    root: Path, scheme_id: int, config_path: Path = CONFIG_PATH, *, set_id: int | None = None
) -> dict:
    """Check and collect everything a geocoding run depends on.

    Args:
        root: Data repository root.
        scheme_id: Harmonization scheme.
        config_path: Geocoding YAML.
        set_id: Set; defaults to the scheme's initial set.

    Returns:
        Set id, classified CSV path, place data and OSM data (manifests only, no rows; OSM is
        None without OSM data), configuration and fingerprint.

    Raises:
        ValueError: If the classification output is missing or stale, or no place data exists.
        RuntimeError: If a hashed file is missing or modified.
    """
    status = classification.output_status(root, scheme_id, set_id=set_id)
    if not status["has_output"]:
        raise ValueError("No classification output; run `nap-tool classify` first")
    if status["stale"]:
        raise ValueError(
            f"Classification output is stale ({status['reason']}); rerun `nap-tool classify` "
            "with the default configuration first"
        )
    set_id = classification.selected_set(root, scheme_id, set_id)
    directory, manifest = classification.saved_output(root, scheme_id, set_id=set_id)
    place_data = load_place_data(root, with_places=False)
    config = load_config(config_path)
    if set(place_data.manifest["object_classes"] or []) != set(config.place_data.object_classes):
        raise ValueError(
            "Place data was built with other object classes than configured; "
            "run `nap-tool place-data fetch`"
        )
    osm = load_osm(root, with_objects=False)
    if osm is not None and set(osm.manifest["classes"]) != set(config.osm.classes):
        raise ValueError(
            "OSM data was fetched for other classes than configured; "
            "run `nap-tool place-data osm-fetch`"
        )
    try:
        parts = {
            "classification": manifest["fingerprint"],
            "classified": manifest["hashes"]["classified.csv"],
        }
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"Malformed classification manifest: {error!r}") from error
    parts["place_data"] = place_data.manifest["places_sha256"]
    parts["place_data_source"] = place_data.manifest["sha256"]
    parts["osm_objects"] = osm.manifest["objects_sha256"] if osm else ""
    parts["osm_source"] = osm.manifest["sha256"] if osm else ""
    fingerprint = hashlib.sha256(json_bytes({**parts, "config": config.model_dump()})).hexdigest()
    return dict(
        set_id=set_id,
        classified=directory / "classified.csv",
        place_data=place_data,
        osm=osm,
        config=config,
        fingerprint=fingerprint,
    )


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Rows and headers of the classified table.

    Args:
        path: Path of ``classified.csv``.

    Returns:
        The rows and the header names.

    Raises:
        ValueError: If the table already has geocode columns.
    """
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    if set(headers) & set(GEOCODE_FIELDS):
        raise ValueError("Classified table already contains geocode columns")
    return rows, headers


def manifest_summary(manifest: dict, version: str) -> dict[str, str]:
    """Source, version and attribution of stored place or OSM data for the report.

    Args:
        manifest: Manifest of the data version.
        version: The data version.

    Returns:
        Source, version, hash, data status and attribution.
    """
    return {
        "source": manifest["source"],
        "version": version,
        "sha256": manifest["sha256"],
        "data_status": manifest["data_status"],
        "attribution": manifest["attribution"],
    }


def saved_output(root: Path, scheme_id: int, set_id: int) -> tuple[Path, dict]:
    """Published generation of a set, verified against its manifest.

    Args:
        root: Data repository root.
        scheme_id: Harmonization scheme.
        set_id: Set.

    Returns:
        The generation directory and its run manifest.

    Raises:
        FileNotFoundError: If there is no pointer or it names a deleted generation.
        ValueError: If the output belongs to another set or scheme.
        RuntimeError: If a file is missing or modified, or the manifest is malformed.
    """
    directory = published_directory(resolve_path(root, f"geocoded/set_{set_id}"), scheme_id)
    manifest = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not {"fingerprint", "hashes"} <= manifest.keys():
        raise RuntimeError("Malformed geocoding manifest: missing fingerprint or hashes")
    if manifest.get("scheme_id") != scheme_id or manifest.get("set_id") != set_id:
        raise ValueError("Geocoded output belongs to a different set or scheme")
    try:
        for name in OUTPUT_FILES:
            relative = (directory / name).relative_to(root.resolve())
            checked_file(root, str(relative), manifest["hashes"][name])
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"Malformed geocoding manifest: {error!r}") from error
    return directory, manifest


def run(
    root: Path, scheme_id: int, config_path: Path = CONFIG_PATH, *, set_id: int | None = None
) -> GeocodeResult:
    """Geocode a set's current classification output and publish a new generation.

    Args:
        root: Data repository root.
        scheme_id: Harmonization scheme.
        config_path: Geocoding YAML.
        set_id: Set; defaults to the scheme's initial set.

    Returns:
        The geocoding result.

    Raises:
        ValueError: If the scheme or set is unknown, an input is missing or stale, another
            run holds the lock, or the input changed during the run.
        RuntimeError: If a hashed file is missing or modified.
    """
    root = root.resolve()
    set_id = classification.selected_set(root, scheme_id, set_id)
    parent = resolve_path(root, f"geocoded/set_{set_id}")
    with scheme_lock(parent, scheme_id, "Geocoding is already running for this scheme"):
        state = inputs(root, scheme_id, config_path, set_id=set_id)
        rows, headers = read_rows(state["classified"])
        matching = state["config"].matching
        place_data = load_place_data(root)
        matcher = Matcher(place_data.places, matching.suffix_words)
        osm = load_osm(root)
        objects = ObjectMatcher(osm.objects, state["config"].osm) if osm else None
        result = geocode_rows(
            rows, matcher, matching.max_anchor_km, matching.min_anchor_points, objects
        )
        stored, stored_osm = state["place_data"], state["osm"]
        result.report["place_data"] = manifest_summary(stored.manifest, stored.version)
        result.report["osm_objects"] = (
            manifest_summary(stored_osm.manifest, stored_osm.version) if stored_osm else None
        )
        contents = {
            "geocoded.csv": csv_bytes(result.rows, headers + GEOCODE_FIELDS),
            "geocoded.geojson": json_bytes(
                {"type": "FeatureCollection", "features": result.features}
            ),
            "geocode_report.md": markdown_report(result.report).encode(),
            "geocode_report.json": json_bytes(result.report),
            "unresolved_names.csv": csv_bytes(result.unresolved, UNRESOLVED_FIELDS),
        }
        manifest = dict(
            fingerprint=state["fingerprint"],
            scheme_id=scheme_id,
            set_id=set_id,
            place_data_sha256=stored.manifest["sha256"],
            osm_objects_sha256=stored_osm.manifest["sha256"] if stored_osm else "",
            hashes={name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
        )
        contents["run_manifest.json"] = json_bytes(manifest)

        def unchanged() -> None:
            current = inputs(root, scheme_id, config_path, set_id=set_id)
            if current["fingerprint"] != state["fingerprint"]:
                raise ValueError("Input changed during geocoding; run again")

        publish_generation(parent, scheme_id, contents, unchanged)
    return result


def output_status(
    root: Path, scheme_id: int, config_path: Path = CONFIG_PATH, *, set_id: int | None = None
) -> dict:
    """Tell whether a set has geocoded output and whether it is stale.

    Args:
        root: Data repository root.
        scheme_id: Harmonization scheme.
        config_path: Geocoding YAML.
        set_id: Set; defaults to the scheme's initial set.

    Returns:
        ``has_output``, ``stale`` and a ``reason`` for staleness.
    """
    root = root.resolve()
    set_id = classification.selected_set(root, scheme_id, set_id)
    try:
        manifest = saved_output(root, scheme_id, set_id)[1]
    except FileNotFoundError:
        return dict(has_output=False, stale=False, reason="")
    except (ValueError, RuntimeError, OSError) as error:
        return dict(has_output=True, stale=True, reason=str(error))
    try:
        fingerprint = inputs(root, scheme_id, config_path, set_id=set_id)["fingerprint"]
        stale = fingerprint != manifest["fingerprint"]
        reason = (
            "Classification, place data, OSM data or geocoding configuration changed; "
            "rerun geocoding"
            if stale
            else ""
        )
    except (ValueError, RuntimeError, OSError) as error:
        stale, reason = True, str(error)
    return dict(has_output=True, stale=stale, reason=reason)
