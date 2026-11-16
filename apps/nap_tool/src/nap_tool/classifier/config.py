# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Validated, editable domain knowledge for classification."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class RoundConfig(BaseModel):
    year: int
    start: str
    end: str


class AssetRule(BaseModel):
    asset_class: str
    patterns: list[str]
    exclude_patterns: list[str] = Field(default_factory=list)
    location_patterns: list[str] = Field(default_factory=list)
    object_patterns: list[str] = Field(default_factory=list)
    suppress_if_types: list[str] = Field(default_factory=list)
    # Dropped when any other asset type is found (generic grid-section terms).
    fallback_only: bool = False


class AssetCode(BaseModel):
    """Meaning of one code of the column "Betriebsmittel [Zuordnungscodes]"."""

    asset_type: str
    grid_level: str = ""


class AssetCodeSettings(BaseModel):
    """How codes are recognized in the asset_type column and what they mean."""

    code_pattern: str
    separator_pattern: str
    codes: dict[str, AssetCode]
    # line_construction_type values that refine a line_or_cable to a concrete line type.
    line_construction: dict[str, list[str]] = Field(default_factory=dict)


class OverviewCondition(BaseModel):
    field_patterns: dict[str, str] = Field(default_factory=dict)
    nonempty_field_pattern: str | None = None
    empty_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_trigger(self):
        if not self.field_patterns and not self.nonempty_field_pattern:
            raise ValueError("Overview condition needs a field trigger")
        return self


class RecordTypeSettings(BaseModel):
    overview: list[str]
    # Regular expressions on the comparison text of collective_fields.
    collective: list[str]
    overview_conditions: list[OverviewCondition]
    collective_fields: list[str]
    name_field: str
    # Rows naming another measure ("Ersetzt durch lfd. Nr. 278") get no location.
    reference_patterns: list[str] = Field(default_factory=list)
    # Rows with none of these fields, or fewer than min_filled_fields filled content
    # fields, are footers, licence notes or blank rows and are dropped.
    identity_fields: list[str] = Field(default_factory=list)
    metadata_fields: list[str] = Field(default_factory=list)
    min_filled_fields: int = Field(default=2, ge=0)


class VoltageSettings(BaseModel):
    allowed_kv: list[float]
    insulation: dict[str, float]
    ranges: dict[str, tuple[float, float]]
    inference: dict[str, int]
    level_tokens: dict[str, list[str]]
    # Tokens that only indicate a level for station assets ("UW" is also a line endpoint).
    station_level_tokens: dict[str, list[str]] = Field(default_factory=dict)
    # Levels from high to low; neighbours are compatible when checking conflicts.
    level_order: list[str]


class LocationSettings(BaseModel):
    # Removed from the text before locations are searched (IDs, technical prefixes).
    strip_patterns: list[str]
    # Station keyword regexes per location kind; the keyword before a name sets its kind.
    types: dict[str, list[str]]
    stop_words: list[str]
    stop_suffixes: list[str]
    connectors: list[str]
    generic_names: list[str]
    object_ref_pattern: str


class RatioThresholds(BaseModel):
    passing: float = Field(alias="pass", ge=0, le=1)
    warn: float = Field(ge=0, le=1)


class CountThresholds(BaseModel):
    passing: tuple[int, int] = Field(alias="pass")
    warn: tuple[int, int]


class CompactSheetSettings(BaseModel):
    """Relative deviation limits of the compact sheet check."""

    passing: float = Field(alias="pass", ge=0)
    warn: float = Field(ge=0)
    # Sheet costs are in Mio. EUR; the records' reported_amount_eur is in EUR.
    cost_divisor: float = Field(default=1_000_000, gt=0)

    @model_validator(mode="after")
    def check_order(self):
        if self.warn < self.passing:
            raise ValueError("Compact sheet warn limit must not be below pass limit")
        return self


class ValidationSettings(BaseModel):
    dso_count: CountThresholds
    measure_share: RatioThresholds
    vocabulary: RatioThresholds
    coverage: RatioThresholds
    plausibility: dict[str, tuple[float, float]]
    compact_sheet: CompactSheetSettings | None = None


class ClassifyConfig(BaseModel):
    round: RoundConfig
    fields: dict[str, list[str]]
    vocabularies: dict[str, dict[str, list[str]]]
    record_type: RecordTypeSettings
    measure_type: dict[str, list[str]]
    assets: dict[str, AssetRule]
    asset_priority: list[str]
    asset_codes: AssetCodeSettings
    voltage: dict
    locations: dict
    validation: dict
    required_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_rules(self) -> ClassifyConfig:
        if set(self.asset_priority) != set(self.assets):
            raise ValueError("asset_priority must contain every asset type exactly once")
        if len(self.asset_priority) != len(self.assets):
            raise ValueError("asset_priority contains duplicates")
        required_sections = {
            "fields": (self.fields, {"numeric", "date", "text"}),
            "measure_type": (
                self.measure_type,
                {"priority", "new", "replacement", "optimization", "dismantling"},
            ),
            "voltage": (
                self.voltage,
                {
                    "allowed_kv",
                    "insulation",
                    "ranges",
                    "inference",
                    "level_tokens",
                    "level_order",
                },
            ),
            "locations": (
                self.locations,
                {
                    "strip_patterns",
                    "types",
                    "stop_words",
                    "stop_suffixes",
                    "connectors",
                    "generic_names",
                    "object_ref_pattern",
                },
            ),
            "validation": (
                self.validation,
                {"dso_count", "measure_share", "vocabulary", "coverage", "plausibility"},
            ),
            "vocabularies": (
                self.vocabularies,
                {
                    "project_category",
                    "project_status",
                    "permit_status",
                    "grid_level",
                    "primary_driver",
                    "existing_bottleneck",
                    "forecast_bottleneck",
                },
            ),
        }
        for section, (values, required) in required_sections.items():
            if required - values.keys():
                raise ValueError(f"Missing configuration keys in {section}")
        self.voltage = VoltageSettings.model_validate(self.voltage).model_dump()
        self.locations = LocationSettings.model_validate(self.locations).model_dump()
        self.validation = ValidationSettings.model_validate(self.validation).model_dump(
            by_alias=True
        )
        if not {"HV", "LV"} <= self.voltage["inference"].keys():
            raise ValueError("Voltage inference defaults must specify HV and LV")
        patterns = [
            p
            for rule in self.assets.values()
            for p in rule.patterns
            + rule.exclude_patterns
            + rule.location_patterns
            + rule.object_patterns
        ]
        patterns += [
            p for key, values in self.measure_type.items() if key != "priority" for p in values
        ]
        for condition in self.record_type.overview_conditions:
            patterns += list(condition.field_patterns.values())
            if condition.nonempty_field_pattern:
                patterns.append(condition.nonempty_field_pattern)
        patterns += self.locations["strip_patterns"] + [self.locations["object_ref_pattern"]]
        patterns += [p for values in self.locations["types"].values() for p in values]
        patterns += self.locations["stop_suffixes"]
        patterns += self.record_type.collective + self.record_type.reference_patterns
        patterns += [self.asset_codes.code_pattern, self.asset_codes.separator_pattern]
        for tokens in ("level_tokens", "station_level_tokens"):
            patterns += [p for values in self.voltage[tokens].values() for p in values]
        if set(self.measure_type["priority"]) != set(self.measure_type) - {"priority"}:
            raise ValueError("Measure priority must contain each measure rule")
        folded = [p for rule in self.assets.values() for p in rule.patterns + rule.exclude_patterns]
        folded += [
            p for key, values in self.measure_type.items() if key != "priority" for p in values
        ]
        folded += self.record_type.collective
        for tokens in ("level_tokens", "station_level_tokens"):
            folded += [p for values in self.voltage[tokens].values() for p in values]
        for pattern in folded:
            if "ß" in pattern:
                raise ValueError(
                    f"Use 'ss' instead of 'ß' in {pattern!r}: texts are compared case-folded"
                )
        for pattern in patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except (re.error, TypeError) as error:
                raise ValueError(f"Invalid classification regex: {pattern}") from error
        for rule in self.assets.values():
            if rule.asset_class not in {"line", "station", "other"}:
                raise ValueError("Unknown asset class")
        levels = set(self.voltage["level_order"])
        if set(self.vocabularies["grid_level"]) - {"all"} != levels:
            raise ValueError("level_order must list every grid_level vocabulary code except all")
        for tokens in ("level_tokens", "station_level_tokens"):
            if set(self.voltage[tokens]) - levels:
                raise ValueError(f"Unknown grid level in voltage.{tokens}")
        for code in self.asset_codes.codes.values():
            if code.asset_type not in self.assets:
                raise ValueError(f"Unknown asset type for code: {code.asset_type}")
            if code.grid_level and code.grid_level not in levels:
                raise ValueError(f"Unknown grid level for code: {code.grid_level}")
        if set(self.asset_codes.line_construction) - set(self.assets):
            raise ValueError("Unknown asset type in asset_codes.line_construction")
        for value in (self.round.start, self.round.end):
            if not re.fullmatch(r"\d{4}-\d{2}", value):
                raise ValueError("Round boundaries must be YYYY-MM")
            date.fromisoformat(value + "-01")
        if self.round.start > self.round.end:
            raise ValueError("Round start is after end")
        for name in ("measure_share", "vocabulary", "coverage"):
            thresholds = self.validation[name]
            if not 0 <= thresholds["warn"] <= thresholds["pass"] <= 1:
                raise ValueError(f"Invalid validation thresholds: {name}")
        for name in ("pass", "warn"):
            low, high = self.validation["dso_count"][name]
            if not 0 <= low <= high:
                raise ValueError("Invalid DSO count range")
        return self


# Anchored to the repository root so classification works from any working directory.
CONFIG_PATH = Path(__file__).resolve().parents[3] / "config/classify.yaml"


def load_config(path: Path = CONFIG_PATH) -> ClassifyConfig:
    with path.open(encoding="utf-8") as source:
        try:
            return ClassifyConfig.model_validate(yaml.safe_load(source))
        except yaml.YAMLError as error:
            raise ValueError(f"Invalid classification YAML: {error}") from error
