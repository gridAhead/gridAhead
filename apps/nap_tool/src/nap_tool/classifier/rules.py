# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Internal deterministic semantic derivation rules."""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date

from .config import ClassifyConfig

NORMALIZED_FIELDS = [
    "project_category",
    "project_status",
    "permit_status",
    "grid_level",
    "primary_driver",
    "existing_bottleneck",
    "forecast_bottleneck",
]
LIST_SEPARATOR = ","
NORMALIZED_OUTPUT = {
    field: "inferred_grid_level" if field == "grid_level" else f"inferred_{field}"
    for field in NORMALIZED_FIELDS
}
DERIVED_FIELDS = [
    "row_id",
    "nap_round",
    "document_date",
    "dso_name",
    "dso_mastr_nr",
    "dso_bdew_code",
    "inferred_record_type",
    *[NORMALIZED_OUTPUT[key] for key in NORMALIZED_FIELDS if key != "grid_level"],
    "inferred_measure_type",
    "inferred_asset_class",
    "inferred_asset_type",
    "inferred_asset_types",
    "inferred_grid_level",
    "inferred_voltage",
    "inferred_line_capacity_change_mva",
    "inferred_station_capacity_change_mva",
    "inferred_location_start",
    "inferred_location_start_kind",
    "inferred_location_end",
    "inferred_location_end_kind",
    "inferred_location_via",
    "inferred_object_ref",
    "inferred_quality_classification",
    "inferred_quality_location",
    "inferred_flags",
]


def comparison(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", re.sub(r"-\s*\n\s*", "", text)).strip()


def words(text: str) -> str:
    """Comparison text in which underscores separate words ("UW_Süd_Neubau")."""
    return comparison(text.replace("_", " "))


def valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
        return False
    try:
        date.fromisoformat(value + {4: "-01-01", 7: "-01", 10: ""}[len(value)])
        return True
    except ValueError:
        return False


def date_outside(value: str, start: str, end: str) -> bool:
    # A year-only date is outside only if its entire interval is outside the window.
    lower = value + {4: "-01-01", 7: "-01", 10: ""}[len(value)]
    if len(value) == 4:
        upper = value + "-12-31"
    elif len(value) == 7:
        year, month = map(int, value.split("-"))
        upper = value + f"-{calendar.monthrange(year, month)[1]:02d}"
    else:
        upper = value
    return upper < start + "-01" or lower[:7] > end


def normalize(value: str, field: str, config: ClassifyConfig) -> str:
    key = comparison(value).replace(" ", "")
    vocab = config.vocabularies[field]
    lookup = {
        comparison(word).replace(" ", ""): code
        for code, words in vocab.items()
        for word in [code, *words]
    }
    if field == "grid_level":
        key = re.sub(r"\(ne\d\)", "", key)
        key = re.sub(r"^ne", "", key)
    if key in lookup:
        return lookup[key]
    if field == "project_category":
        # Recognize a complete sequence of known categories, including PDF lists
        # without separators. Unknown fragments must not become plausible categories.
        remaining, codes = key, []
        words = sorted(lookup, key=len, reverse=True)
        while remaining:
            word = next((word for word in words if remaining.startswith(word)), None)
            if not word:
                break
            codes.append(lookup[word])
            remaining = remaining[len(word) :]
            remaining = re.sub(r"^(?:[;,/]+|und)+", "", remaining)
        if codes and not remaining:
            return codes[0]
        for part in re.split(r"[;\n]", value):
            found = lookup.get(comparison(part).replace(" ", ""))
            if found:
                return found
    if field == "grid_level":
        parts = re.split(r"[,;]", key)
        if len(parts) > 1 and all(part in lookup for part in parts):
            return LIST_SEPARATOR.join(dict.fromkeys(lookup[part] for part in parts))
        if key in {"hs/ms", "hös/hs", "ms/ns"}:
            return lookup.get(key, "")
    return ""


def record_type(row: dict[str, str], config: ClassifyConfig) -> str:
    settings = config.record_type
    name = comparison(row.get(settings.name_field, ""))
    for condition in settings.overview_conditions:
        if any(row.get(field, "").strip() for field in condition.empty_fields):
            continue
        if not all(
            re.search(pattern, comparison(row.get(field, "")))
            for field, pattern in condition.field_patterns.items()
        ):
            continue
        if condition.nonempty_field_pattern and not any(
            value.strip() and re.search(condition.nonempty_field_pattern, key)
            for key, value in row.items()
        ):
            continue
        return "overview"
    if any(name.startswith(comparison(word)) for word in settings.overview):
        return "overview"
    text = comparison(" ".join(row.get(key, "") for key in settings.collective_fields))
    if any(re.search(pattern, text) for pattern in settings.collective):
        return "collective"
    return "measure"


def is_filler(row: dict[str, str], config: ClassifyConfig) -> bool:
    """Tell whether a row is a footer, licence note or blank row rather than a measure.

    Args:
        row: Input row with stable field keys.
        config: Classification configuration.

    Returns:
        True when no identity field is filled or fewer than ``min_filled_fields`` content
        fields are filled.
    """
    settings = config.record_type
    if settings.identity_fields and not any(
        row.get(key, "").strip() for key in settings.identity_fields
    ):
        return True
    filled = {
        value.strip()
        for key, value in row.items()
        if key not in settings.metadata_fields and value and value.strip()
    }
    return len(filled) < settings.min_filled_fields


def asset_codes(value: str, config: ClassifyConfig) -> list[str] | None:
    """Parse a cell of asset codes such as ``501. 601``, ``401, 801`` or ``501601``.

    Args:
        value: Raw asset_type cell.
        config: Classification configuration.

    Returns:
        The distinct codes in source order, or None when the cell is not only codes and
        separators (free text such as "MS-Kabel").
    """
    settings = config.asset_codes
    tokens = re.sub(settings.separator_pattern, " ", value).split()
    codes: list[str] = []
    for token in tokens:
        if not token.isdigit() or len(token) % 3:
            return None
        chunks = [token[index : index + 3] for index in range(0, len(token), 3)]
        if not all(re.fullmatch(settings.code_pattern, chunk) for chunk in chunks):
            return None
        codes += [chunk for chunk in chunks if chunk not in codes]
    return codes or None


def named_station(key: str, text: str, config: ClassifyConfig) -> bool:
    """Tell whether a station type appears only as a named place ("ST Mühlenstr. > ST X").

    Args:
        key: Asset type key.
        text: Comparison text.
        config: Classification configuration.

    Returns:
        True for a station type matched by a location pattern and no object pattern.
    """
    rule = config.assets[key]
    return (
        rule.asset_class == "station"
        and any(re.search(pattern, text) for pattern in rule.location_patterns)
        and not any(re.search(pattern, text) for pattern in rule.object_patterns)
    )


def station_mentions(text: str, config: ClassifyConfig) -> int:
    """Count station keywords followed by a name; two or more are the ends of a route.

    Args:
        text: Comparison text.
        config: Classification configuration.

    Returns:
        Number of named stations ("uw kirchen > st börnchenstr." gives 2).
    """
    keywords = "|".join(
        keyword
        for kind, values in config.locations["types"].items()
        if kind != "search_area"
        for keyword in values
    )
    return len(re.findall(rf"\b(?:{keywords})\b\.?\s*[:\s]\s*[^\W\d_]", text))


def text_assets(text: str, config: ClassifyConfig, *, from_text: bool) -> list[str]:
    """Asset types named in one text, in priority order.

    Args:
        text: Comparison text of a cell.
        config: Classification configuration.
        from_text: True for measure names and descriptions, where a named station next to
            another asset is usually a location ("Trafotausch UW X").

    Returns:
        Asset type keys.
    """
    found = [
        key
        for key in config.asset_priority
        if any(re.search(pattern, text) for pattern in config.assets[key].patterns)
    ]
    found = [
        key
        for key in found
        if not any(re.search(pattern, text) for pattern in config.assets[key].exclude_patterns)
    ]
    found = [
        key
        for key in found
        if not any(other in found for other in config.assets[key].suppress_if_types)
    ]
    if from_text and sum(not config.assets[key].fallback_only for key in found) > 1:
        found = [key for key in found if not named_station(key, text, config)]
    specific = [key for key in found if not config.assets[key].fallback_only]
    return specific or found


def detect_assets(
    row: dict[str, str], config: ClassifyConfig, primary_level: str = ""
) -> tuple[list[str], list[str], str]:
    """Detect asset types from the asset cell, the name, the description and asset codes.

    Args:
        row: Input row with stable field keys.
        config: Classification configuration.
        primary_level: Reported grid level; among code-derived types, the type of the code
            on this level comes first.

    Returns:
        Asset types (primary first), the parsed asset codes, and the source of the
        primary type: ``asset_type``, ``measure_name``, ``measure_description``,
        ``asset_codes`` or "".
    """
    raw = row.get("asset_type", "")
    codes = asset_codes(raw, config) or []
    sources = [
        ("measure_name", row.get("measure_name", "")),
        ("measure_description", row.get("measure_description", "")),
    ]
    if raw and not codes:
        sources.insert(0, ("asset_type", raw))
    found, source, fallback, named = [], "", ([], ""), False
    for name, text in sources:
        hits = text_assets(words(text), config, from_text=name != "asset_type")
        if hits and not all(config.assets[key].fallback_only for key in hits):
            found, source = hits, name
            named = (
                name != "asset_type"
                and all(named_station(key, words(text), config) for key in hits)
                and station_mentions(words(text), config) >= 2
            )
            break
        if hits and not fallback[0]:
            fallback = (hits, name)
    known = [config.asset_codes.codes[code] for code in codes if code in config.asset_codes.codes]
    known.sort(key=lambda code: code.grid_level != primary_level)
    code_types = list(dict.fromkeys(code.asset_type for code in known))
    lines = [key for key in code_types if config.assets[key].asset_class == "line"]
    if code_types and not found:
        found, source = code_types, "asset_codes"
    elif lines and named:
        # The text only names stations (route ends); the code says what is built.
        found, source = list(dict.fromkeys(lines + found)), "asset_codes"
    elif code_types:
        classes = {config.assets[key].asset_class for key in found}
        found += [
            key
            for key in code_types
            if key not in found and config.assets[key].asset_class not in classes
        ]
    if not found and fallback[0]:
        found, source = fallback
    if not found and row.get("capacity_change_basis") == "substation":
        found, source = ["substation"], "capacity_change_basis"
    if not found and raw:
        found, source = ["other"], "asset_type"
    construction = comparison(row.get("line_construction_type", ""))
    for target, values in config.asset_codes.line_construction.items():
        if construction in {comparison(value) for value in values}:
            found = [target if key == "line_or_cable" else key for key in found]
            found = list(dict.fromkeys(found))
    return found, codes, source


def level_for_kv(kv: float, config: ClassifyConfig) -> str:
    return next(
        (level for level, (low, high) in config.voltage["ranges"].items() if low <= kv <= high), ""
    )


def voltage_values(
    row: dict[str, str], config: ClassifyConfig, *, include_pairs: bool = False
) -> tuple[list[float], list[tuple[float, float]]]:
    """Nominal voltages in kV named in the text fields.

    Args:
        row: Input row with stable field keys.
        config: Classification configuration.
        include_pairs: Also return both sides of transformation ratios as single values.

    Returns:
        Single voltages and transformation pairs ("110/20 kV"), each mapped to allowed
        nominal voltages.
    """

    def nominal(token: str) -> float:
        kv = float(token.replace(",", "."))
        return float(config.voltage["insulation"].get(f"{kv:g}", kv))

    text = comparison(" ".join(row.get(key, "") for key in config.fields["text"]))
    pattern = r"(\d+(?:[.,]\d+)?)\s*-?\s*/\s*(\d+(?:[.,]\d+)?)\s*-?\s*kv"
    pairs = []
    for match in re.finditer(pattern, text):
        pair = (nominal(match.group(1)), nominal(match.group(2)))
        if all(kv in config.voltage["allowed_kv"] for kv in pair) and pair not in pairs:
            pairs.append(pair)
    text = re.sub(pattern, "", text)
    values = [kv for pair in pairs for kv in pair] if include_pairs else []
    for token in re.findall(r"(\d+(?:[.,]\d+)?)\s*-?\s*kv", text):
        kv = nominal(token)
        if kv in config.voltage["allowed_kv"]:
            values.append(kv)
    return list(dict.fromkeys(values)), pairs


def text_levels(row: dict[str, str], config: ClassifyConfig, station_like: bool) -> list[str]:
    """Grid levels named in the text through voltages or level tokens.

    Args:
        row: Input row with stable field keys.
        config: Classification configuration.
        station_like: Whether the asset is a station, so station-only tokens apply.

    Returns:
        Levels in source order; transformation tokens dominate their component tokens.
    """
    values, pairs = voltage_values(row, config)
    levels = [
        "/".join(level_for_kv(kv, config) for kv in pair)
        for pair in pairs
        if level_for_kv(pair[0], config) != level_for_kv(pair[1], config)
    ]
    levels = list(dict.fromkeys(levels + [level_for_kv(kv, config) for kv in values]))
    levels = [level for level in levels if level in config.voltage["level_order"]]
    if levels:
        return levels
    text = words(" ".join(row.get(key, "") for key in config.fields["text"][:3]))

    def found(tokens: dict[str, list[str]]) -> list[str]:
        return [
            level
            for level in config.voltage["level_order"]
            if any(re.search(pattern, text) for pattern in tokens.get(level, []))
        ]

    levels = found(config.voltage["level_tokens"])
    if not levels and station_like:
        # "UW" names a station level only when nothing more specific is written.
        levels = found(config.voltage["station_level_tokens"])
    transformations = [level for level in levels if "/" in level]
    return transformations or levels


def compatible(first: str, second: str, config: ClassifyConfig) -> bool:
    """Tell whether two levels are equal or neighbours ("HV" and "HV/MV")."""
    order = config.voltage["level_order"]
    if first not in order or second not in order:
        return first == second
    return abs(order.index(first) - order.index(second)) <= 1


def derive_levels(
    reported: str,
    codes: list[str],
    row: dict[str, str],
    out: dict[str, str],
    config: ClassifyConfig,
) -> tuple[list[str], set[str]]:
    """Grid levels: the reported level first, then the levels of the asset codes.

    Without reported level and codes, the levels named in the text are used. A line
    cannot sit on a transformation level, so text-derived ones become the line's level.

    Args:
        reported: Normalized grid_level value (comma-separated if several).
        codes: Parsed asset codes.
        row: Input row with stable field keys.
        out: Derived values so far (asset class).
        config: Classification configuration.

    Returns:
        Levels and quality flags.
    """
    flags: set[str] = set()
    order = config.voltage["level_order"]
    from_codes = sorted(
        {
            config.asset_codes.codes[code].grid_level
            for code in codes
            if code in config.asset_codes.codes and config.asset_codes.codes[code].grid_level
        },
        key=order.index,
    )
    levels = [level for level in reported.split(LIST_SEPARATOR) if level]
    levels += [level for level in from_codes if level not in levels]
    station_like = out["inferred_asset_class"] in {"station", ""}
    mentioned = text_levels(row, config, station_like)
    if levels:
        explicit = [level for level in levels if level != "all"]
        if (
            mentioned
            and explicit
            and not any(compatible(level, text, config) for level in explicit for text in mentioned)
        ):
            flags.add("grid_level_conflict")
        return levels, flags
    if out["inferred_asset_class"] == "line":
        values, _ = voltage_values(row, config)
        single = [level_for_kv(values[0], config)] if len(values) == 1 else []
        mentioned = list(
            dict.fromkeys(
                (single[0] if single else level.split("/")[-1]) if "/" in level else level
                for level in mentioned
            )
        )
    flags.add("grid_level_inferred" if mentioned else "grid_level_missing")
    return mentioned, flags


def derive_voltage(
    levels: list[str],
    row: dict[str, str],
    config: ClassifyConfig,
    unusual_hv: set[str],
) -> tuple[str, set[str]]:
    """Nominal voltage in V per grid level, aligned with the levels.

    A level takes the single voltage of that level named in the text; HV and LV fall back
    to the configured default. A transformation level is "upper/lower" when both sides
    are known. Unknown entries stay empty.

    Args:
        levels: Grid levels of the row.
        row: Input row with stable field keys.
        config: Classification configuration.
        unusual_hv: DSOs whose texts name a high voltage other than the default.

    Returns:
        Comma-separated voltages ("" when none is known) and quality flags.
    """
    flags: set[str] = set()
    values, pairs = voltage_values(row, config)
    defaults = config.voltage["inference"]

    def single(level: str) -> str:
        candidates = [kv for kv in values if level_for_kv(kv, config) == level]
        candidates += [kv for pair in pairs for kv in pair if level_for_kv(kv, config) == level]
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            return str(round(candidates[0] * 1000))
        if len(candidates) > 1:
            flags.add("voltage_ambiguous")
            return ""
        if level in defaults and (level != "HV" or row.get("dso_slug", "") not in unusual_hv):
            flags.add("voltage_inferred")
            return str(defaults[level])
        return ""

    if len(levels) == 1 and "/" not in levels[0] and len(values) == 1 and not pairs:
        if level_for_kv(values[0], config) != levels[0]:
            # An explicit voltage beats the level default ("220 kV" on a reported HV line).
            flags.add("voltage_other_level")
            return str(round(values[0] * 1000)), flags
    result = []
    for level in levels:
        if "/" not in level:
            result.append(single(level) if level in config.voltage["level_order"] else "")
            continue
        upper, lower = level.split("/")
        pair = next(
            (
                pair
                for pair in pairs
                if (level_for_kv(pair[0], config), level_for_kv(pair[1], config)) == (upper, lower)
            ),
            None,
        )
        if pair:
            result.append("/".join(str(round(kv * 1000)) for kv in pair))
            continue
        sides = [single(upper), single(lower)]
        result.append("/".join(sides) if all(sides) else "")
    return (LIST_SEPARATOR.join(result) if any(result) else ""), flags


def object_refs(row: dict[str, str], config: ClassifyConfig) -> str:
    """Grid object IDs (line, plant and station numbers) in the name and description."""
    refs: list[str] = []
    for key in ("measure_name", "measure_description"):
        for match in re.finditer(config.locations["object_ref_pattern"], row.get(key, "")):
            ref = re.sub(r"\s+", " ", match.group(0))
            if ref not in refs:
                refs.append(ref)
    return LIST_SEPARATOR.join(refs)
