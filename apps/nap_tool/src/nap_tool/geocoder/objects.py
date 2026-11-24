# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Grid objects (substations, plants) matched by name, kind, operator and distance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .config import OsmSettings
from .match import Place, Resolution, distance_km
from .normalize import normalize, without_qualifier


@dataclass(frozen=True)
class GridObject:
    """One named OSM object with a point."""

    id: str
    cls: str
    name: str
    operator: str
    ref: str
    voltage: str
    lat: float
    lon: float

    def as_place(self) -> Place:
        """The object as a ``Place`` with source ``osm`` and its OSM class."""
        return Place(self.id, self.name, "", self.cls, "", self.lat, self.lon, 0, source="osm")


class ObjectMatcher:
    """Find the grid object a location name refers to.

    Args:
        objects: Named OSM objects.
        settings: Kind-to-class map, station words, operator stop words and distance limit.
    """

    def __init__(self, objects: Iterable[GridObject], settings: OsmSettings) -> None:
        self.kinds = settings.kinds
        self.rescue_only_kinds = set(settings.rescue_only_kinds)
        self.max_km = settings.max_km
        self.strip = {normalize(word) for word in settings.strip_words}
        self.operator_stop = {normalize(word) for word in settings.operator_stop_words}
        self.index: dict[str, list[GridObject]] = defaultdict(list)
        for item in objects:
            names = [item.name, without_qualifier(item.name) or ""]
            for key in {self.key(name) for name in names if name}:
                if key:
                    self.index[key].append(item)

    def key(self, name: str) -> str:
        """Normalized name without station words; '' if nothing is left."""
        return " ".join(word for word in normalize(name).split() if word not in self.strip)

    def operator_words(self, text: str) -> set[str]:
        """Words of an operator or DSO name that identify it."""
        return {w for w in normalize(text).split() if len(w) > 2 and w not in self.operator_stop}

    def find(
        self,
        name: str,
        kind: str,
        near: tuple[float, float] | None,
        dso_name: str,
        *,
        max_km: float | None = None,
    ) -> Resolution | None:
        """The grid object a location name refers to, if there is a plausible one.

        Args:
            name: Location name from classification.
            kind: Location kind from classification.
            near: Settlement point of the location, else the DSO anchor, else None. Without a
                reference point nothing can be checked for plausibility, so nothing matches.
            dso_name: Name of the DSO, to prefer objects it operates.
            max_km: Farthest distance from ``near``; None uses the configured ``osm.max_km``.

        Returns:
            A resolved ``osm_<class>`` resolution, or None.
        """
        classes = self.kinds.get(kind)
        key = self.key(name)
        if near is None or not classes or not key:
            return None
        found = [item for item in self.index.get(key, ()) if item.cls in classes]
        wanted = self.operator_words(dso_name)
        preferred = [item for item in found if wanted & self.operator_words(item.operator)]
        found = preferred or found
        limit = self.max_km if max_km is None else max_km
        close = [i for i in found if distance_km(near, (i.lat, i.lon)) <= limit]
        chosen = min(close, key=lambda i: (distance_km(near, (i.lat, i.lon)), i.id), default=None)
        if chosen is None:
            return None
        return Resolution("resolved", f"osm_{chosen.cls}", chosen.as_place())
