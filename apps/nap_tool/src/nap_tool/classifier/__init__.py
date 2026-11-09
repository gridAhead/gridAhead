# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Classify rows without changing any source field or performing I/O."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import ClassifyConfig
from .locations import LocationFinder
from .rules import (
    DERIVED_FIELDS,
    LIST_SEPARATOR,
    NORMALIZED_FIELDS,
    NORMALIZED_OUTPUT,
    comparison,
    date_outside,
    derive_levels,
    derive_voltage,
    detect_assets,
    is_filler,
    level_for_kv,
    normalize,
    object_refs,
    record_type,
    valid_date,
    voltage_values,
)
from .validation import validate

LINE_LEVELS = {"HV", "MV", "LV"}
CLASSIFICATION_ISSUES = {
    "asset_type_from_description",
    "asset_type_from_codes",
    "asset_type_from_grid_level",
    "grid_level_inferred",
}
CLASSIFICATION_PROBLEMS = {"asset_type_missing", "grid_level_missing", "grid_level_conflict"}
LOCATION_ISSUES = {
    "location_source:measure_description",
    "location_hyphen_split",
    "location_route_split",
    "location_multiple",
    "location_end_missing",
}


@dataclass
class ClassificationResult:
    rows: list[dict[str, str]]
    report: dict
    unmapped: list[dict[str, str | int]]


def derive_locations(
    row: dict[str, str], out: dict[str, str], finder: LocationFinder, config: ClassifyConfig
) -> set[str]:
    """Fill the location columns of a measure from its name, description or site name.

    Args:
        row: Input row with stable field keys.
        out: Derived values; the location columns are filled in place.
        finder: Location finder built from the configuration.
        config: Classification configuration.

    Returns:
        Location flags.
    """
    name = row.get("measure_name", "").strip()
    if any(re.search(pattern, name, re.I) for pattern in config.record_type.reference_patterns):
        return {"refers_to_other_measure"}
    generic = {comparison(item) for item in config.locations["generic_names"]}
    line_like = out["inferred_asset_class"] == "line"
    sources = [
        ("measure_name", "" if comparison(name) in generic else name, False),
        ("measure_description", row.get("measure_description", ""), True),
        ("site_name", row.get("site_name", ""), False),
    ]
    for source, text, strict in sources:
        found = finder.find(text, line_like, strict)
        if not found.places:
            continue
        flags = {f"location_source:{source}"}
        flags |= {
            f"location_{kind}_split"
            for kind in ("hyphen", "route")
            if found.how == f"endpoints_{kind}"
        }
        places = found.places
        if line_like:
            (out["inferred_location_start"], out["inferred_location_start_kind"]) = places[0]
            if len(places) > 1:
                (out["inferred_location_end"], out["inferred_location_end_kind"]) = places[-1]
                out["inferred_location_via"] = LIST_SEPARATOR.join(item[0] for item in places[1:-1])
            else:
                flags.add("location_end_missing")
        else:
            out["inferred_location_start"] = ", ".join(item[0] for item in places[:3])
            out["inferred_location_start_kind"] = places[0][1]
            if len(places) > 1 and found.how != "plain":
                flags.add("location_multiple")
        return flags
    return {"location_missing"}


def quality(out: dict[str, str], flags: set[str]) -> None:
    """Grade the asset/grid-level classification and the location separately.

    Args:
        out: Derived values; the two quality columns are filled in place.
        flags: Flags of the row.
    """
    if not out["inferred_asset_type"] and not out["inferred_grid_level"]:
        out["inferred_quality_classification"] = "none"
    elif flags & CLASSIFICATION_PROBLEMS:
        out["inferred_quality_classification"] = "low"
    elif flags & CLASSIFICATION_ISSUES:
        out["inferred_quality_classification"] = "medium"
    else:
        out["inferred_quality_classification"] = "high"
    if out["inferred_record_type"] == "collective" or "refers_to_other_measure" in flags:
        out["inferred_quality_location"] = "not_applicable"
    elif not out["inferred_location_start"]:
        out["inferred_quality_location"] = "none"
    elif flags & LOCATION_ISSUES:
        out["inferred_quality_location"] = "medium"
    else:
        out["inferred_quality_location"] = "high"


def classify(
    rows: list[dict[str, str]],
    config: ClassifyConfig,
    dso_identifiers: dict[str, dict[str, str]],
    *,
    field_mapping: dict[str, str] | None = None,
) -> ClassificationResult:
    """Append derived columns to harmonized rows and validate the result.

    Source fields are never changed. Footer, licence and blank rows are dropped and
    listed in the report.

    Args:
        rows: Harmonized rows.
        config: Classification configuration.
        dso_identifiers: Name, MaStR number and BDEW code per DSO slug.
        field_mapping: Stable field keys mapped to the original CSV headers.

    Returns:
        Classified rows, validation report and unmapped vocabulary values.

    Raises:
        ValueError: If a row already has derived columns or invalid provenance.
    """
    mapping = field_mapping or {}
    inputs = [
        {**row, **{key: row.get(header, "") for key, header in mapping.items()}} for row in rows
    ]
    finder = LocationFinder(config)
    outputs, kept, origins, unresolved, dropped = [], [], [], [], []
    unmatched = {}
    seen = {}
    unusual_hv = {
        row.get("dso_slug", "")
        for row in inputs
        for kv in voltage_values(row, config, include_pairs=True)[0]
        if level_for_kv(kv, config) == "HV"
        and round(kv * 1000) != config.voltage["inference"]["HV"]
    }
    for original, row in zip(rows, inputs):
        if set(original) & set(DERIVED_FIELDS):
            raise ValueError("Input already contains derived classification fields")
        try:
            provenance = json.loads(row["source_cells_json"])
            origin = provenance["origin"]
            if not isinstance(origin, dict):
                raise ValueError("origin must be an object")
            extract, number = origin["extract_table_id"], origin["row_number"]
            if (
                not isinstance(extract, int)
                or isinstance(extract, bool)
                or extract < 1
                or not isinstance(number, int)
                or isinstance(number, bool)
                or number < 1
            ):
                raise ValueError("Source table and row identifiers must be positive integers")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid source_cells_json: {error}") from error
        out = dict.fromkeys(DERIVED_FIELDS, "")
        out["row_id"] = f"{extract}-{number}"
        kind = record_type(row, config)
        if kind != "overview" and is_filler(row, config):
            dropped.append(dict(row_id=out["row_id"], dso=row.get("dso_slug", "")))
            continue
        origins.append(origin)
        kept.append(row)
        flags = set()
        out["nap_round"] = str(config.round.year)
        document_date = str(origin.get("currentFrom") or "")
        if document_date:
            if valid_date(document_date):
                out["document_date"] = document_date
                if date_outside(document_date, config.round.start, config.round.end):
                    flags.add("document_outside_round")
            else:
                flags.add("unresolved:document_date")
                unresolved.append(
                    dict(
                        document=origin.get("document_id"),
                        table=extract,
                        field="document_date",
                        value=document_date,
                    )
                )
        codes = dso_identifiers.get(row.get("dso_slug", ""), {})
        for field, key in [
            ("dso_name", "name"),
            ("dso_mastr_nr", "mastr_nr"),
            ("dso_bdew_code", "bdew_code"),
        ]:
            out[field] = codes.get(key) or ""
        out["inferred_record_type"] = kind
        numeric = {}
        numeric_fields = config.fields["numeric"] + [
            key for key in row if key.startswith("investment_") and key.endswith("_eur")
        ]
        for field in dict.fromkeys(numeric_fields + config.fields["date"]):
            value = row.get(field, "")
            if not value:
                continue
            valid = (
                bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value))
                if field in numeric_fields
                else (valid_date(value))
            )
            if not valid:
                flags.add(f"unresolved:{field}")
                unresolved.append(
                    dict(
                        document=origin.get("document_id"), table=extract, field=field, value=value
                    )
                )
                continue
            if field in numeric_fields:
                numeric[field] = value
                limits = config.validation["plausibility"].get(field)
                if limits:
                    number_value = float(value)
                    if not limits[0] <= number_value <= limits[1] or (
                        field == "reported_amount_eur" and number_value == 0
                    ):
                        flags.add(f"implausible:{field}")
        normalized = {}
        for field in NORMALIZED_FIELDS:
            value = row.get(field, "")
            normalized[field] = normalize(value, field, config) if value else ""
            if value and not normalized[field]:
                flags.add(f"unmapped:{field}")
                key = (field, comparison(value).replace(" ", ""))
                entry = unmatched.setdefault(
                    key, dict(field=field, value=value, count=0, dsos=set())
                )
                entry["count"] += 1
                entry["dsos"].add(row.get("dso_slug", ""))
            out[NORMALIZED_OUTPUT[field]] = normalized[field]
        if kind != "overview":
            flags |= classify_measure(row, out, normalized, numeric, (config, finder, unusual_hv))
        identity = tuple(
            (key, value) for key, value in sorted(original.items()) if key != "source_cells_json"
        )
        if identity in seen:
            flags.add(f"duplicate_of={seen[identity]}")
        else:
            seen[identity] = out["row_id"]
        out["inferred_flags"] = LIST_SEPARATOR.join(sorted(flags))
        outputs.append({**original, **out})
    unmapped = [
        dict(
            field=item["field"],
            value=item["value"],
            count=item["count"],
            dso_slugs=LIST_SEPARATOR.join(sorted(item["dsos"])),
        )
        for item in unmatched.values()
    ]
    unmapped.sort(key=lambda item: (item["field"], -item["count"], item["value"]))
    report = validate(outputs, kept, origins, config, unresolved)
    report["dropped_rows"] = dropped
    return ClassificationResult(outputs, report, unmapped)


def classify_measure(
    row: dict[str, str],
    out: dict[str, str],
    normalized: dict[str, str],
    numeric: dict[str, str],
    context: tuple[ClassifyConfig, LocationFinder, set[str]],
) -> set[str]:
    """Derive asset, measure type, grid level, voltage, capacity, location and quality.

    Args:
        row: Input row with stable field keys.
        out: Derived values; filled in place.
        normalized: Normalized vocabulary values of the row.
        numeric: Valid numeric values of the row.
        context: Configuration, location finder and DSOs with an unusual high voltage.

    Returns:
        Flags of the row.
    """
    config, finder, unusual_hv = context
    flags: set[str] = set()
    primary_level = normalized["grid_level"].split(LIST_SEPARATOR)[0]
    assets, codes, source = detect_assets(row, config, primary_level)
    source_flag = {
        "measure_description": "asset_type_from_description",
        "asset_codes": "asset_type_from_codes",
    }.get(source)
    if source_flag:
        flags.add(source_flag)
    if assets:
        out["inferred_asset_class"] = config.assets[assets[0]].asset_class
    levels, level_flags = derive_levels(normalized["grid_level"], codes, row, out, config)
    if (
        not assets
        and out["inferred_record_type"] == "measure"
        and levels
        and set(levels) <= LINE_LEVELS
        and finder.find(row.get("measure_name", ""), True, False).how.startswith("endpoints")
    ):
        # A route between two places on a line level is a line ("ENB: Bassum-Weyhe", HS).
        assets = ["line_or_cable"]
        out["inferred_asset_class"] = "line"
        flags.add("asset_type_from_grid_level")
    if assets:
        out["inferred_asset_types"] = LIST_SEPARATOR.join(assets)
        out["inferred_asset_type"] = assets[0]
    else:
        flags.add("asset_type_missing")
    if out["inferred_asset_class"] == "line":
        out["inferred_line_capacity_change_mva"] = numeric.get("capacity_change_mva", "")
    elif out["inferred_asset_class"] == "station":
        out["inferred_station_capacity_change_mva"] = numeric.get(
            "substation_capacity_change_mva", numeric.get("capacity_change_mva", "")
        )
    elif row.get("capacity_change_mva") or row.get("substation_capacity_change_mva"):
        flags.add("capacity_unassigned")
    out["inferred_measure_type"] = normalized["project_category"]
    if not out["inferred_measure_type"]:
        text = comparison(row.get("measure_name", "") + " " + row.get("measure_description", ""))
        for kind in config.measure_type["priority"]:
            if any(re.search(pattern, text) for pattern in config.measure_type[kind]):
                out["inferred_measure_type"] = kind
                flags.add("measure_type_source:text")
                break
        capacity = (
            out["inferred_station_capacity_change_mva"] or out["inferred_line_capacity_change_mva"]
        )
        if out["inferred_measure_type"] == "replacement" and capacity:
            if float(capacity) > 0:
                out["inferred_measure_type"] = "replacement_increase"
            elif float(capacity) == 0:
                out["inferred_measure_type"] = "replacement_no_increase"
    flags |= level_flags
    out["inferred_grid_level"] = LIST_SEPARATOR.join(levels)
    out["inferred_voltage"], voltage_flags = derive_voltage(levels, row, config, unusual_hv)
    flags |= voltage_flags
    out["inferred_object_ref"] = object_refs(row, config)
    if out["inferred_record_type"] == "measure":
        flags |= derive_locations(row, out, finder, config)
    quality(out, flags)
    return flags
