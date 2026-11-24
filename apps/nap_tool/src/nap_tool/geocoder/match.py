# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Place data lookup, DSO anchors and candidate choice (pure, no I/O)."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Iterator, Literal

from .normalize import normalize, without_qualifier

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Place:
    """One settlement or municipality of the place data, or an OSM object.

    ``source`` is ``gn250`` for place data and ``osm`` for an OSM object, whose
    ``object_class`` is then its OSM class (``substation``, ``plant``).
    """

    id: str
    name: str
    name2: str
    object_class: str
    ags: str
    lat: float
    lon: float
    population: int
    source: str = "gn250"


@dataclass(frozen=True)
class Lookup:
    """Candidates for one name and the step that found them ('' when none)."""

    step: str
    candidates: tuple[Place, ...]


@dataclass(frozen=True)
class Resolution:
    """The chosen place for one name, or why there is none.

    ``detail`` is the step name for a resolved place, the reason when unresolved and the
    location kind when skipped.
    """

    kind: Literal["resolved", "unresolved", "skipped"]
    detail: str
    place: Place | None = None

    @property
    def status(self) -> str:
        """The status as written: step, ``unresolved:<reason>`` or ``skipped:<kind>``."""
        return self.detail if self.kind == "resolved" else f"{self.kind}:{self.detail}"


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) points in kilometres.

    Args:
        first: Latitude and longitude in decimal degrees.
        second: Latitude and longitude in decimal degrees.

    Returns:
        Distance in kilometres.
    """
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def index_keys(place: Place) -> set[str]:
    """Normalized names a place is found under: name, long name, both without qualifier.

    Args:
        place: PlaceData place.

    Returns:
        Non-empty normalized keys.
    """
    names = [place.name, place.name2]
    names += [without_qualifier(name) or "" for name in names if name]
    return {key for key in (normalize(name) for name in names if name) if key}


class Matcher:
    """Find place data candidates for a name with the ordered fallback steps.

    Args:
        places: PlaceData places.
        suffix_words: Trailing words removed in step ``strip_suffix`` ('Nord', 'Mitte').
    """

    def __init__(self, places: Iterable[Place], suffix_words: Iterable[str]) -> None:
        self.index: dict[str, list[Place]] = defaultdict(list)
        for place in places:
            for key in index_keys(place):
                self.index[key].append(place)
        self.suffix_words = {normalize(word) for word in suffix_words}

    def candidates(self, name: str) -> tuple[Place, ...]:
        """Places under a name; one per municipality, the most populous.

        Places without an AGS are kept apart (keyed by their id).

        Args:
            name: Name as written.

        Returns:
            Candidates ordered by id.
        """
        best: dict[str, Place] = {}
        for place in self.index.get(normalize(name), []):
            key = place.ags or place.id
            current = best.get(key)
            if current is None or (-place.population, place.id) < (
                -current.population,
                current.id,
            ):
                best[key] = place
        return tuple(sorted(best.values(), key=lambda place: place.id))

    def variants(self, name: str, street: bool) -> Iterator[tuple[str, str]]:
        """Names to try, in step order; a street address tries only its comma parts.

        Args:
            name: Name as written.
            street: Whether the name is a street address.

        Yields:
            Step name and the name variant to look up.
        """
        parts = [part.strip() for part in name.split(",") if part.strip()]
        if not street:
            yield "exact", name
        if len(parts) > 1:
            for part in parts:
                yield "comma_part", part
        if street:
            return
        words = normalize(name).split()
        if len(words) > 1 and words[-1] in self.suffix_words:
            yield "strip_suffix", " ".join(words[:-1])
        stripped = without_qualifier(name)
        if stripped:
            yield "strip_qualifier", stripped

    def lookup(self, name: str, street: bool = False) -> Lookup:
        """Candidates of the first step that finds any.

        Args:
            name: Name as written.
            street: Whether the name is a street address.

        Returns:
            The step and its candidates; step '' and no candidates when nothing is found.
        """
        for step, variant in self.variants(name, street):
            found = self.candidates(variant)
            if found:
                return Lookup(step, found)
        return Lookup("", ())


def dso_anchors(unique: dict[str, set[Place]], min_points: int) -> dict[str, tuple[float, float]]:
    """Median point of each DSO's unambiguous exact matches.

    Args:
        unique: Distinct places per DSO slug that matched exactly one candidate in ``exact``.
        min_points: Fewest places a DSO needs for an anchor.

    Returns:
        (lat, lon) per DSO slug with enough places.
    """
    return {
        slug: (
            statistics.median(place.lat for place in places),
            statistics.median(place.lon for place in places),
        )
        for slug, places in unique.items()
        if len(places) >= min_points
    }


def choose(lookup: Lookup, anchor: tuple[float, float] | None, max_km: float) -> Resolution:
    """Pick the place for a lookup.

    Args:
        lookup: Candidates and the step that found them.
        anchor: The DSO's anchor, if any.
        max_km: Farthest distance from the anchor an ambiguous candidate may have.

    Returns:
        The step name (or ``nearest_to_anchor``) with the place, or ``unresolved:<reason>``.
    """
    if not lookup.candidates:
        return Resolution("unresolved", "no_match")
    if len(lookup.candidates) == 1:
        return Resolution("resolved", lookup.step, lookup.candidates[0])
    if anchor is None:
        return Resolution("unresolved", "ambiguous_no_anchor")
    nearest = min(
        lookup.candidates,
        key=lambda place: (distance_km(anchor, (place.lat, place.lon)), place.id),
    )
    if distance_km(anchor, (nearest.lat, nearest.lon)) > max_km:
        return Resolution("unresolved", "ambiguous_far")
    return Resolution("resolved", "nearest_to_anchor", nearest)
