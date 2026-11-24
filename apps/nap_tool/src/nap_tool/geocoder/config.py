# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Loading and validating config/geocode.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Anchored to the app root (apps/nap_tool) so geocoding works from any working directory.
CONFIG_PATH = Path(__file__).resolve().parents[3] / "config/geocode.yaml"


class PlaceDataSettings(BaseModel):
    """Where GN250 comes from and which of its object classes are kept."""

    model_config = ConfigDict(extra="forbid")

    url: str
    member: str = "gn250/GN250.csv"
    object_classes: list[str] = Field(default_factory=lambda: ["AX_Gemeinde", "AX_Ortslage"])


class MatchSettings(BaseModel):
    """Fallback words and DSO anchor limits."""

    model_config = ConfigDict(extra="forbid")

    suffix_words: list[str] = Field(default_factory=list)
    max_anchor_km: float = Field(100, gt=0)
    min_anchor_points: int = Field(3, ge=1)


class OsmSettings(BaseModel):
    """OSM objects: what to store and how location kinds match them."""

    model_config = ConfigDict(extra="forbid")

    overpass_url: str = "https://overpass-api.de/api/interpreter"
    classes: list[str] = Field(default_factory=lambda: ["substation", "plant"])
    kinds: dict[str, list[str]] = Field(default_factory=dict)
    rescue_only_kinds: list[str] = Field(default_factory=list)
    strip_words: list[str] = Field(default_factory=list)
    operator_stop_words: list[str] = Field(default_factory=list)
    max_km: float = Field(15, gt=0)

    @model_validator(mode="after")
    def check_kinds(self) -> OsmSettings:
        """Reject kinds that point at classes which are not stored."""
        unknown = {c for classes in self.kinds.values() for c in classes} - set(self.classes)
        if unknown:
            raise ValueError(f"osm.kinds uses classes not in osm.classes: {sorted(unknown)}")
        return self


class GeocodeConfig(BaseModel):
    """Top-level shape of config/geocode.yaml."""

    model_config = ConfigDict(extra="forbid")

    place_data: PlaceDataSettings
    matching: MatchSettings = Field(default_factory=MatchSettings)
    osm: OsmSettings = Field(default_factory=OsmSettings)


def load_config(path: Path = CONFIG_PATH) -> GeocodeConfig:
    """Load and validate the geocoding configuration.

    Args:
        path: Geocoding YAML.

    Returns:
        Validated configuration.

    Raises:
        ValueError: If the YAML is malformed or does not match the schema.
    """
    with path.open(encoding="utf-8") as source:
        try:
            return GeocodeConfig.model_validate(yaml.safe_load(source))
        except yaml.YAMLError as error:
            raise ValueError(f"Invalid geocoding YAML: {error}") from error
