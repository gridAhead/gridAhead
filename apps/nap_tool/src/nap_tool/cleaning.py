# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic, column-configured cleaning of reviewed extraction grids."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class UnitGroup(BaseModel):
    """Canonical unit and exact unit conversion factors."""

    canonical: str
    aliases: dict[str, Decimal]


class CleaningGlobals(BaseModel):
    """Shared unit and missing-value definitions."""

    units: dict[str, UnitGroup]
    null_tokens: list[str]

    @model_validator(mode="after")
    def check_aliases(self) -> CleaningGlobals:
        """Reject unit aliases that would have ambiguous dimensions."""
        seen: dict[str, str] = {}
        for group_name, group in self.units.items():
            for alias in group.aliases:
                key = alias.casefold()
                if key in seen and seen[key] != group_name:
                    raise ValueError(f"Unit alias {alias} appears in multiple groups")
                seen[key] = group_name
        return self


class ColumnRule(BaseModel):
    """One source column's cleaning rule."""

    index: int = Field(ge=0)
    kind: Literal["text", "money", "number", "date", "choice"] = "text"
    configured: bool = False
    source_unit: str = ""
    target_unit: str = ""
    choices: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_choices(self) -> ColumnRule:
        """Reject duplicate choice spellings with conflicting standard values."""
        seen: set[str] = set()
        for standard, aliases in self.choices.items():
            for value in [standard, *aliases]:
                key = value.strip().casefold()
                if not key or key in seen:
                    raise ValueError(f"Duplicate or empty choice: {value}")
                seen.add(key)
        return self


class CleanConfig(BaseModel):
    """Versioned configuration for a complete extracted table."""

    header_row: int = Field(default=1, ge=1)
    decimal_separator: Literal[",", "."] = ","
    thousands_separator: Literal[".", ",", "", " "] = "."
    columns: list[ColumnRule] = Field(default_factory=list)
    deleted_rows: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_columns(self) -> CleanConfig:
        """Ensure each source column has at most one rule and deleted rows are data rows."""
        if any(row < self.header_row for row in self.deleted_rows):
            raise ValueError("Header and preamble rows cannot be deleted")
        self.deleted_rows = sorted(set(self.deleted_rows))
        indexes = [column.index for column in self.columns]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Duplicate column rule index")
        if self.decimal_separator == self.thousands_separator:
            raise ValueError("Decimal and thousands separators must differ")
        return self


def load_cleaning_globals(path: Path) -> CleaningGlobals:
    """Read and validate shared cleaning definitions.

    Args:
        path: YAML configuration path.

    Returns:
        Validated cleaning definitions.
    """
    with path.open(encoding="utf-8") as source:
        return CleaningGlobals.model_validate(yaml.safe_load(source))


MACHINE_FORMAT_TOOLS = frozenset({"xlsx"})


def default_config(headers: list[str], header_row: int = 1, tool: str = "") -> CleanConfig:
    """Suggest safe initial column rules from source headers.

    Args:
        headers: Selected CSV header row.
        header_row: One-based physical CSV row containing the headers.
        tool: Extraction tool of the table. Spreadsheet importers write numeric cells in
            machine format (``0.102``), so their tables get ``.`` as decimal separator and
            no thousands separator.

    Returns:
        Initial cleaning configuration.
    """
    columns: list[ColumnRule] = []
    for index, header in enumerate(headers):
        lowered = header.casefold()
        match = re.search(r"\[([^]]+)\]", header)
        source_unit = re.sub(r"^(?:\+/-|±)\s*", "", match.group(1).strip()) if match else ""
        kind: Literal["text", "money", "number", "date", "choice"] = "text"
        if "€" in header or "kosten" in lowered or "investition" in lowered:
            kind = "money"
        elif any(word in lowered for word in ("jahr", "zeitpunkt", "datum", "inbetriebnahme")):
            kind = "date"
        elif source_unit in ("km", "m", "MVA", "kVA", "MW", "kW", "Stück"):
            kind = "number"
        columns.append(ColumnRule(index=index, kind=kind, source_unit=source_unit))
    return with_tool_number_format(CleanConfig(header_row=header_row, columns=columns), tool)


def with_tool_number_format(config: CleanConfig, tool: str) -> CleanConfig:
    """Use the machine number format for spreadsheet tables that still have the text default.

    Spreadsheet importers render numeric cells as ``repr(float)``. With the default German
    format, ``0.102`` (km) would be read as the thousands group ``102``. A separator choice
    that differs from the default was made by a reviewer and is kept.

    Args:
        config: Cleaning configuration to check.
        tool: Extraction tool of the table.

    Returns:
        The configuration, with ``.``/no thousands separator for spreadsheet tables that
        still use the default ``,``/``.``.
    """
    if tool not in MACHINE_FORMAT_TOOLS or (
        config.decimal_separator,
        config.thousands_separator,
    ) != (",", "."):
        return config
    return config.model_copy(update={"decimal_separator": ".", "thousands_separator": ""})


def normalize(value: str) -> str:
    """Join broken words and normalize whitespace without changing meaning."""
    value = re.sub(r"-\s*\r?\n\s*(?=[a-zäöüß])", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _number(value: str, config: CleanConfig) -> Decimal:
    value = value.replace("\u00a0", " ").replace(" ", "")
    if not re.fullmatch(r"[+-]?[0-9][0-9.,]*", value):
        raise ValueError("Not a single number")
    decimal = config.decimal_separator
    thousands = config.thousands_separator
    if "." in value and "," in value:
        decimal = "." if value.rfind(".") > value.rfind(",") else ","
        thousands = "," if decimal == "." else "."
    elif not thousands and value.count(".") + value.count(",") == 1:
        # Without a thousands separator a single separator can only be the decimal mark,
        # e.g. typed text "2,85" in a spreadsheet whose numeric cells use ".".
        value = value.replace(",", ".")
        decimal = "."
    elif thousands and thousands in value and decimal not in value:
        groups = value.lstrip("+-").split(thousands)
        if len(groups) > 1 and all(len(group) == 3 and group.isdigit() for group in groups[1:]):
            return Decimal(value.replace(thousands, ""))
        decimal = thousands
        thousands = ""
    if thousands:
        value = value.replace(thousands, "")
    if decimal != ".":
        value = value.replace(decimal, ".")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Could not parse number format") from error


def _unit_value(
    value: str, rule: ColumnRule, config: CleanConfig, globals_config: CleaningGlobals
) -> str:
    aliases = sorted(
        (
            (alias, group_name, factor)
            for group_name, group in globals_config.units.items()
            for alias, factor in group.aliases.items()
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    explicit = ""
    number_text = value
    for alias, _, _ in aliases:
        if value.casefold().endswith(alias.casefold()):
            number_text = value[: -len(alias)].strip()
            explicit = alias
            break
    number = _number(number_text, config)
    source_unit = explicit or rule.source_unit
    if rule.kind == "money":
        target_group = "money"
        target_unit = "€"
    else:
        target_unit = rule.target_unit or rule.source_unit or explicit
        target_group = next(
            (
                name
                for name, group in globals_config.units.items()
                if target_unit == group.canonical or target_unit in group.aliases
            ),
            None,
        )
    if source_unit:
        matching = next(
            (
                (name, factor)
                for alias, name, factor in aliases
                if alias.casefold() == source_unit.casefold()
            ),
            None,
        )
        if matching is None or target_group is None or matching[0] != target_group:
            raise ValueError(f"Unit mismatch: {source_unit}")
        factor = matching[1]
    else:
        factor = Decimal(1)
    if rule.kind == "number" and target_unit:
        group = globals_config.units[target_group]
        denominator = group.aliases.get(target_unit)
        if denominator is None:
            raise ValueError(f"Unknown target unit: {target_unit}")
        number = number * factor / denominator
    else:
        number *= factor
    return format(number.normalize(), "f")


def _iso_date(value: str) -> str:
    """Validate a ``YYYY`` or ``YYYY-MM`` value and return it unchanged."""
    if len(value) == 7 and not 1 <= int(value[5:]) <= 12:
        raise ValueError("Could not parse date format")
    return value


MONTHS = {
    "jan": 1,
    "jän": 1,
    "feb": 2,
    "mär": 3,
    "märz": 3,
    "mrz": 3,
    "apr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dez": 12,
}


def _date(value: str) -> str:
    if re.fullmatch(r"\d{4}(?:-\d{2})?", value):
        return _iso_date(value)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?", value)
    if match:
        # Spreadsheet datetimes carry time-zone artefacts such as 01:00; keep the day.
        return date.fromisoformat(match.group(1)).isoformat()
    match = re.fullmatch(r"(\d{1,2})/(\d{4})", value)
    if match and 1 <= int(match.group(1)) <= 12:
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if match:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    match = re.fullmatch(r"([A-Za-zÄÖÜäöü]{3,4})\.?\s+(\d{2}|\d{4})", value)
    if match and match.group(1).casefold() in MONTHS:
        year = int(match.group(2))
        if year < 100:
            year += 2000
        return f"{year:04d}-{MONTHS[match.group(1).casefold()]:02d}"
    raise ValueError("Could not parse date format")


def clean_cell(
    original: str, rule: ColumnRule, config: CleanConfig, globals_config: CleaningGlobals
) -> tuple[str, str, str]:
    """Clean one cell while keeping unparsed input visible.

    Args:
        original: Raw source value.
        rule: Column rule.
        config: Table number format.
        globals_config: Shared definitions.

    Returns:
        Clean value, status, and explanation.
    """
    value = normalize(original)
    if value.casefold() in {token.casefold() for token in globals_config.null_tokens}:
        return "", "converted", "Placeholder converted to an empty value"
    if not value:
        return "", "unchanged" if value == original else "converted", ""
    try:
        if rule.kind in ("money", "number"):
            result = _unit_value(value, rule, config, globals_config)
        elif rule.kind == "date":
            result = _date(value)
        elif rule.kind == "choice":
            result = next(
                standard
                for standard, aliases in rule.choices.items()
                if value.casefold() in {item.casefold() for item in [standard, *aliases]}
            )
        else:
            result = value
    except (ValueError, StopIteration) as error:
        return original, "unresolved", str(error) or "Not in the choice list"
    return result, "converted" if result != original else "unchanged", ""


def kept_row_indexes(row_count: int, config: CleanConfig) -> list[int]:
    """List the source row indexes that survive row deletion.

    Args:
        row_count: Number of source CSV rows including header.
        config: Cleaning version rules.

    Returns:
        Zero-based source row indexes in order.
    """
    deleted = set(config.deleted_rows)
    return [index for index in range(row_count) if index not in deleted]


def clean_grid(
    rows: list[list[str]], config: CleanConfig, globals_config: CleaningGlobals
) -> tuple[list[list[str]], list[dict[str, str | int]]]:
    """Apply column rules to all data rows and record changed or failed cells.

    Args:
        rows: Source CSV rows including header.
        config: Cleaning version rules.
        globals_config: Shared cleaning definitions.

    Returns:
        Cleaned rows and sparse cell status records.
    """
    rules = {column.index: column for column in config.columns}
    if rows and config.header_row > len(rows):
        raise ValueError("Header row is outside the table")
    width = max(map(len, rows), default=0)
    output = [list(row) + [""] * (width - len(row)) for row in rows[: config.header_row]]
    statuses: list[dict[str, str | int]] = []
    deleted = set(config.deleted_rows)
    for row_index, row in enumerate(rows[config.header_row :], start=config.header_row):
        if row_index in deleted:
            continue
        result_row: list[str] = []
        for column_index in range(width):
            original = row[column_index] if column_index < len(row) else ""
            rule = rules.get(column_index, ColumnRule(index=column_index))
            value, status, note = clean_cell(original, rule, config, globals_config)
            result_row.append(value)
            if status != "unchanged":
                statuses.append(
                    {
                        "row": row_index,
                        "column": column_index,
                        "original": original,
                        "status": status,
                        "note": note,
                    }
                )
        output.append(result_row)
    return output, statuses


def csv_bytes(rows: list[list[str]]) -> bytes:
    """Encode a CSV grid with stable line endings."""
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue().encode("utf-8")
