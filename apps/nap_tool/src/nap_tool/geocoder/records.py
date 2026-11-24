# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Geocode the start and end locations of classified records (pure, no I/O)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .match import Lookup, Matcher, Place, Resolution, choose, distance_km, dso_anchors
from .objects import ObjectMatcher

ROLES = ("start", "end")
STATION_KINDS = {"substation", "switching_station", "local_substation"}
SKIPPED_KINDS = {"code"}
UNRESOLVED_FIELDS = ["name", "kind", "reason", "count", "dso_slugs"]


def role_fields(role: str) -> list[str]:
    """Geocode columns of one role: lat, lon, match, geocode, precision.

    Args:
        role: ``start`` or ``end``.

    Returns:
        The five column names of that role.
    """
    prefix = f"inferred_location_{role}"
    return [
        f"{prefix}_lat",
        f"{prefix}_lon",
        f"{prefix}_match",
        f"{prefix}_geocode",
        f"{prefix}_precision",
    ]


GEOCODE_FIELDS = [name for role in ROLES for name in role_fields(role)]


@dataclass
class GeocodeResult:
    """Geocoded rows, point features, report data and unresolved names."""

    rows: list[dict[str, str]]
    features: list[dict]
    report: dict
    unresolved: list[dict[str, str | int]] = field(default_factory=list)


@dataclass(frozen=True)
class Location:
    """One start or end location of one record."""

    row: int
    role: str
    dso: str
    name: str
    kind: str
    dso_name: str = ""

    @property
    def key(self) -> tuple[str, bool]:
        """Lookup key: the name and whether it is a street address."""
        return self.name, self.kind == "street_address"


@dataclass(frozen=True)
class Outcome:
    """The resolution of one location."""

    location: Location
    resolution: Resolution
    unique: bool  # the lookup had exactly one candidate
    station: bool = False  # a resolved place of a station kind
    rescued: bool = False  # an OSM object found where the settlement lookup failed

    @property
    def place(self) -> Place | None:
        """The resolved place, if any."""
        return self.resolution.place

    @property
    def status(self) -> str:
        """The geocode status as written to the output."""
        return self.resolution.status + ("+station" if self.station else "")

    @property
    def precision(self) -> str:
        """``object`` for an OSM position, ``settlement`` for a GN250 centre, '' if unresolved."""
        if self.place is None:
            return ""
        return "object" if self.place.source == "osm" else "settlement"


def locations(rows: list[dict[str, str]]) -> list[Location]:
    """Start and end locations of measure records, in row order.

    Args:
        rows: Classified rows.

    Returns:
        One location per non-empty start or end name of a measure record.
    """
    found = []
    for index, row in enumerate(rows):
        if row.get("inferred_record_type") != "measure":
            continue
        for role in ROLES:
            name = row.get(f"inferred_location_{role}", "").strip()
            if name:
                kind = row.get(f"inferred_location_{role}_kind", "")
                found.append(
                    Location(
                        index, role, row.get("dso_slug", ""), name, kind, row.get("dso_name", "")
                    )
                )
    return found


def skip_kind(location: Location) -> str:
    """The location kind of a location that is not geocoded, else ''.

    A street address is only geocoded through its comma parts, so it needs at least two.

    Args:
        location: Location to check.

    Returns:
        The kind to report as ``skipped:<kind>``, or '' when the location is looked up.
    """
    if location.kind in SKIPPED_KINDS:
        return location.kind
    if location.kind == "street_address":
        parts = [part for part in location.name.split(",") if part.strip()]
        if len(parts) < 2:
            return "street_address"
    return ""


def refine(
    location: Location,
    resolution: Resolution,
    anchor: tuple[float, float] | None,
    objects: ObjectMatcher | None,
    anchor_km: float,
) -> Resolution | None:
    """The OSM object for a location, or None to keep the settlement result.

    Near a settlement point the configured ``osm.max_km`` applies; a rescue near the DSO
    anchor uses the anchor's own scale ``anchor_km``.

    Args:
        location: Location to refine.
        resolution: Its settlement resolution.
        anchor: Anchor of the location's DSO.
        objects: Object matcher, if OSM data exists.
        anchor_km: Farthest distance of an object from the DSO anchor.

    Returns:
        A resolved OSM resolution, or None.
    """
    if objects is None:
        return None
    place = resolution.place
    if place is None:
        return objects.find(
            location.name, location.kind, anchor, location.dso_name, max_km=anchor_km
        )
    if location.kind in objects.rescue_only_kinds:
        return None
    return objects.find(location.name, location.kind, (place.lat, place.lon), location.dso_name)


def resolve(
    targets: list[Location],
    matcher: Matcher,
    max_km: float,
    min_points: int,
    objects: ObjectMatcher | None = None,
) -> tuple[list[Outcome], dict[str, tuple[float, float]], dict[str, set[Place]]]:
    """Look every location up, build the DSO anchors and choose a place per location.

    Args:
        targets: Locations to geocode.
        matcher: PlaceData lookup.
        max_km: Farthest distance from the DSO anchor for an ambiguous choice and an OSM
            rescue.
        min_points: Fewest unambiguous places a DSO needs for an anchor.
        objects: OSM object matcher; upgrades station-like locations to object positions.

    Returns:
        One outcome per location, the anchor per DSO and the unambiguous exact places per DSO.
    """
    skips = [skip_kind(location) for location in targets]
    lookups: dict[tuple[str, bool], Lookup] = {}
    for location, skipped in zip(targets, skips):
        if not skipped and location.key not in lookups:
            lookups[location.key] = matcher.lookup(*location.key)
    unique: dict[str, set[Place]] = defaultdict(set)
    for location, skipped in zip(targets, skips):
        if skipped:
            continue
        lookup = lookups[location.key]
        if lookup.step == "exact" and len(lookup.candidates) == 1:
            unique[location.dso].add(lookup.candidates[0])
    anchors = dso_anchors(unique, min_points)

    outcomes = []
    for location, skipped in zip(targets, skips):
        if skipped:
            outcomes.append(Outcome(location, Resolution("skipped", skipped), False))
            continue
        lookup = lookups[location.key]
        resolution = choose(lookup, anchors.get(location.dso), max_km)
        hit = refine(location, resolution, anchors.get(location.dso), objects, max_km)
        rescued = hit is not None and resolution.place is None
        if hit is not None:
            resolution = hit
        station = hit is None and resolution.place is not None and location.kind in STATION_KINDS
        single = hit is None and len(lookup.candidates) == 1
        outcomes.append(Outcome(location, resolution, single, station, rescued))
    return outcomes, anchors, unique


def fill_rows(
    rows: list[dict[str, str]],
    outcomes: list[Outcome],
    anchors: dict[str, tuple[float, float]],
    max_km: float,
) -> tuple[list[dict[str, str]], list[dict], list[dict]]:
    """Write the geocode columns and collect point features and far-away matches.

    Args:
        rows: Classified rows; not changed.
        outcomes: Resolution of every location.
        anchors: Anchor per DSO.
        max_km: Distance beyond which a unique match counts as far from its DSO.

    Returns:
        Copies of the rows with the geocode columns, GeoJSON point features, and the unique
        matches farther than ``max_km`` from their DSO anchor.
    """
    output = [{**row, **dict.fromkeys(GEOCODE_FIELDS, "")} for row in rows]
    features: list[dict] = []
    far: list[dict] = []
    for outcome in outcomes:
        location, place = outcome.location, outcome.place
        lat, lon, match, geocode, precision = role_fields(location.role)
        row = output[location.row]
        row[geocode] = outcome.status
        if place is None:
            continue
        row[precision] = outcome.precision
        row[lat], row[lon] = f"{place.lat:.6f}", f"{place.lon:.6f}"
        row[match] = f"{place.name} ({place.ags})" if place.ags else place.name
        details = {
            "row_id": row.get("row_id", ""),
            "role": location.role,
            "dso_slug": location.dso,
            "name": location.name,
            "match": row[match],
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [place.lon, place.lat]},
                "properties": {
                    **details,
                    "geocode": outcome.status,
                    "precision": outcome.precision,
                },
            }
        )
        anchor = anchors.get(location.dso)
        if anchor and outcome.unique:
            distance = distance_km(anchor, (place.lat, place.lon))
            if distance > max_km:
                far.append({**details, "distance_km": round(distance, 1)})
    return output, features, far


def build_report(
    outcomes: list[Outcome],
    far: list[dict],
    anchors: dict[str, tuple[float, float]],
    unique: dict[str, set[Place]],
) -> dict:
    """Counts by status, kind and DSO plus anchors and far-away matches.

    Args:
        outcomes: Resolution of every location.
        far: Unique matches far from their DSO anchor.
        anchors: Anchor per DSO.
        unique: Unambiguous exact places per DSO.

    Returns:
        The report data.
    """
    status_counts: Counter[str] = Counter()
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    by_dso: dict[str, Counter[str]] = defaultdict(Counter)
    for outcome in outcomes:
        status_counts[outcome.status] += 1
        result = outcome.resolution.kind
        for counts in (by_kind[outcome.location.kind], by_dso[outcome.location.dso]):
            counts["total"] += 1
            counts[result] += 1
    total = len(outcomes)
    resolved = sum(1 for outcome in outcomes if outcome.place)
    return {
        "locations": total,
        "resolved": resolved,
        "resolved_share": round(resolved / total, 4) if total else 0.0,
        "by_status": dict(sorted(status_counts.items())),
        "by_kind": {kind: dict(sorted(c.items())) for kind, c in sorted(by_kind.items())},
        "by_dso": {
            slug: {
                **dict(sorted(counts.items())),
                "anchor": list(anchors[slug]) if slug in anchors else None,
                "anchor_points": len(unique.get(slug, ())),
            }
            for slug, counts in sorted(by_dso.items())
        },
        "far_from_dso": far,
        "osm": {
            "matched": sum(1 for o in outcomes if o.precision == "object"),
            "rescued": sum(1 for o in outcomes if o.rescued),
        },
    }


def unresolved_names(outcomes: list[Outcome]) -> list[dict[str, str | int]]:
    """Unresolved names with reason, count and the DSOs that use them.

    Args:
        outcomes: Resolution of every location.

    Returns:
        One entry per (name, kind, reason), most frequent first.
    """
    counts: Counter[tuple[str, str, str]] = Counter()
    dsos: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for outcome in outcomes:
        if outcome.resolution.kind == "unresolved":
            location = outcome.location
            key = (location.name, location.kind, outcome.resolution.detail)
            counts[key] += 1
            dsos[key].add(location.dso)
    return [
        {
            "name": name,
            "kind": kind,
            "reason": reason,
            "count": count,
            "dso_slugs": ",".join(sorted(dsos[(name, kind, reason)])),
        }
        for (name, kind, reason), count in sorted(counts.items(), key=lambda i: (-i[1], i[0]))
    ]


def geocode_rows(
    rows: list[dict[str, str]],
    matcher: Matcher,
    max_km: float,
    min_points: int,
    objects: ObjectMatcher | None = None,
) -> GeocodeResult:
    """Add coordinates and a geocode status to the start and end of every measure.

    Args:
        rows: Classified rows; not changed.
        matcher: PlaceData lookup.
        max_km: Farthest distance from the DSO anchor (ambiguous choice, OSM rescue,
            far_from_dso).
        min_points: Fewest unambiguous places a DSO needs for an anchor.
        objects: OSM object matcher, if OSM data exists.

    Returns:
        Rows with the geocode columns, point features, report data and unresolved names.
    """
    outcomes, anchors, unique = resolve(locations(rows), matcher, max_km, min_points, objects)
    output, features, far = fill_rows(rows, outcomes, anchors, max_km)
    report = build_report(outcomes, far, anchors, unique)
    return GeocodeResult(output, features, report, unresolved_names(outcomes))
