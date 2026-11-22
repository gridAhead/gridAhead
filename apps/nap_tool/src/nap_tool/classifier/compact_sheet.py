# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Compact sheet check: reading the DSO's compact sheet and comparing it with the records."""

from __future__ import annotations

import re
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .rules import LIST_SEPARATOR

ANCHOR = "Erwarteter Netzausbaubedarf bis 2045"
UNNAMED_SUBGRID = "teilnetzgebiet nicht benannt"
CATEGORY_HEADER = "Projektkategorie"

# Sheet label -> (grid level, is a station level).
LEVEL_LABELS = {
    "hochstspannung": None,  # not a template block; guards against a stray label
    "hochst- auf hochspannung": ("EHV/HV", True),
    "hochspannung": ("HV", False),
    "hoch- auf mittelspannung": ("HV/MV", True),
    "mittelspannung": ("MV", False),
    "mittel- auf niederspannung": ("MV/LV", True),
    "niederspannung": ("LV", False),
}
HORIZONS = {
    "2025 bis 2030 (t+5)": "T+5",
    "2031 bis 2035 (t+10)": "T+10",
    "2036 bis 2045 (zielnetz)": "Zielnetz 2045",
}
QUANTITY_HEADERS = {
    "anzahl": "count",
    "mva": "mva",
    "kilometer": "km",
    "geschätzter bedarf": "cost",
}
LINE_QUANTITIES = ("km", "cost")
STATION_QUANTITIES = ("count", "mva", "cost")
CATEGORY_GROUPS = {
    "new": "Neubau",
    "increase": "Ersatz(neubau) mit Erhöhung; Netzoptimierung und -verstärkung",
    "replacement": "Reiner Ersatz (1:1) / Rückbau / Altlastentsorgung",
}
RECORD_CATEGORY_GROUP = {
    "new": "new",
    "replacement_increase": "increase",
    "optimization": "increase",
    "replacement_no_increase": "replacement",
    "dismantling": "replacement",
}
RANK = {"pass": 0, "warn": 1, "fail": 2}


class LayoutError(ValueError):
    """The workbook does not follow the compact sheet template."""


@dataclass
class CompactSheet:
    """The cells of one compact sheet.

    Attributes:
        document_id: Document the sheet was read from.
        error: Reason the sheet could not be parsed ("unexpected layout: ..."), else "".
        subgrids: Subgrid area name -> {(level, horizon, group, quantity): value or None}.
            None is an empty cell (missing); 0 is an explicit "no need".
    """

    document_id: int | None = None
    error: str = ""
    subgrids: dict[str, dict[tuple[str, str, str, str], float | None]] = field(default_factory=dict)


def fold(value: object) -> str:
    """Compare text after whitespace collapse and casefold."""
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # Some DSOs' cells hold text with a unit, e.g. "74.81 Mio. Euro", "140 km", "40.0 MVA".
    match = re.fullmatch(
        r"(-?\d+(?:[.,]\d+)?)\s*(?:mio\.?\s*euro|mio\.?\s*€|mva|km)?", str(value).strip(), re.I
    )
    return float(match.group(1).replace(",", ".")) if match else None


def _category_group(label: object) -> str | None:
    text = fold(label)
    if text.startswith("neubau"):
        return "new"
    if text.startswith("ersatz(neubau) mit erhöhung") or text.startswith("ersatzneubau mit erh"):
        return "increase"
    if text.startswith("reiner ersatz"):
        return "replacement"
    return None


def _sheet(workbook):
    for sheet in workbook.worksheets:
        if fold(sheet["B1"].value).startswith(fold(ANCHOR)):
            return sheet
    raise LayoutError(f"unexpected layout: no sheet with B1 starting '{ANCHOR}'")


def read_compact_sheet(path: Path, document_id: int | None = None) -> CompactSheet:
    """Read the subgrid cells of a compact sheet workbook.

    The template is shared by all DSOs, so the sheet is read from its anchor labels: the
    category header row, the horizon and quantity header rows below the grid-level labels,
    and subgrid triplets (one row per category group) below the headers. The sheet's own
    totals are ignored.

    Args:
        path: XLSX workbook; formulas are read as their cached values.
        document_id: Document id stored in the result.

    Returns:
        The parsed sheet, or one with `error` set when the layout is unexpected.
    """
    import openpyxl

    sheet = CompactSheet(document_id=document_id)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # openpyxl drops unsupported extensions
            workbook = openpyxl.load_workbook(path, data_only=True)
        try:
            sheet.subgrids = _parse(_sheet(workbook))
        finally:
            workbook.close()
    except LayoutError as error:
        sheet.error = str(error)
    except Exception as error:  # unreadable or damaged workbook
        sheet.error = f"unexpected layout: {type(error).__name__}: {error}"
    return sheet


def _parse(ws) -> dict[str, dict[tuple[str, str, str, str], float | None]]:
    header_row = next(
        (r for r in range(1, 40) if fold(ws.cell(r, 2).value) == fold(CATEGORY_HEADER)), None
    )
    if header_row is None:
        raise LayoutError(f"unexpected layout: no '{CATEGORY_HEADER}' header")
    # A note row may sit between the horizon and the quantity headers.
    quantity_row = next(
        (
            r
            for r in range(header_row + 1, header_row + 4)
            if any(fold(c.value) in QUANTITY_HEADERS for c in ws[r])
        ),
        header_row + 1,
    )
    levels = _level_labels(ws, header_row)
    columns = []  # (column, level, horizon, quantity)
    not_operated: set[int] = set()
    horizon_columns = [
        (cell.column, HORIZONS[fold(cell.value)])
        for cell in ws[header_row]
        if fold(cell.value) in HORIZONS
    ]
    if not horizon_columns:
        raise LayoutError("unexpected layout: no planning horizon headers")
    for index, (start, horizon) in enumerate(horizon_columns):
        end = horizon_columns[index + 1][0] if index + 1 < len(horizon_columns) else None
        level = max((c for c in levels if c <= start), default=None)
        if level is None:
            raise LayoutError(f"unexpected layout: no grid level label above column {start}")
        level_name, station = levels[level]
        names = []
        column = start
        while column < (end or start + 4) and column < start + 4:
            quantity = QUANTITY_HEADERS.get(fold(ws.cell(quantity_row, column).value))
            if quantity:
                names.append((column, quantity))
            column += 1
        expected = STATION_QUANTITIES if station else LINE_QUANTITIES
        if not names and (level in not_operated or _not_operated(ws, header_row, level)):
            # "Netzebene wird nicht betrieben": the DSO has no such grid level.
            not_operated.add(level)
            continue
        if tuple(name for _, name in names) != expected:
            raise LayoutError(
                f"unexpected layout: quantity headers of {level_name} {horizon} are "
                f"{[name for _, name in names]}, expected {list(expected)}"
            )
        columns.extend((col, level_name, horizon, name) for col, name in names)
    subgrids: dict[str, dict] = {}
    current = ""
    for row in range(quantity_row + 1, ws.max_row + 1):
        group = _category_group(ws.cell(row, 2).value)
        name = ws.cell(row, 1).value
        if name is not None and str(name).strip():
            current = str(name).strip()
        if group is None:
            if fold(ws.cell(row, 2).value):
                raise LayoutError(
                    f"unexpected layout: unknown project category in B{row}: "
                    f"{ws.cell(row, 2).value!r}"
                )
            continue
        if not current or fold(current) == UNNAMED_SUBGRID:
            continue
        cells = subgrids.setdefault(current, {})
        for column, level_name, horizon, quantity in columns:
            cells[(level_name, horizon, group, quantity)] = _number(ws.cell(row, column).value)
    return subgrids


def _not_operated(ws, header_row: int, column: int) -> bool:
    return any(
        "nicht betrieben" in fold(ws.cell(row, column).value)
        for row in range(max(1, header_row - 8), header_row)
    )


def _level_labels(ws, header_row: int) -> dict[int, tuple[str, bool]]:
    """Grid-level label cells (column -> level) from the rows above the header row."""
    best: dict[int, tuple[str, bool]] = {}
    for row in range(max(1, header_row - 8), header_row):
        found = {}
        for cell in ws[row]:
            level = LEVEL_LABELS.get(fold(cell.value).replace("ö", "o").replace("ü", "u"))
            if level:
                found[cell.column] = level
        if len(found) > len(best):
            best = found
    if not best:
        raise LayoutError("unexpected layout: no grid level labels")
    return best


@dataclass
class Totals:
    """Record totals per key, plus what could not be placed."""

    # (subgrid casefolded or "" for none, level, horizon, group, quantity) -> value
    values: dict[tuple[str, str, str, str, str], float] = field(
        default_factory=lambda: defaultdict(float)
    )
    names: dict[str, str] = field(default_factory=dict)
    unassigned_horizons: int = 0


def _horizon(value: str) -> str:
    text = fold(value)
    for horizon in ("T+5", "T+10", "Zielnetz 2045"):
        if text == horizon.casefold():
            return horizon
    return ""


def record_totals(
    rows: list[dict[str, str]],
    inputs: list[dict[str, str]],
    config: dict,
) -> dict[str, Totals]:
    """Sum the classified records of the round per DSO.

    Args:
        rows: Classified rows.
        inputs: The rows' source values by stable field key.
        config: `validation.compact_sheet` settings.

    Returns:
        Totals by DSO slug.
    """
    divisor = config["cost_divisor"]
    totals: dict[str, Totals] = defaultdict(Totals)
    for row, source in zip(rows, inputs):
        if row["inferred_record_type"] not in {"measure", "collective"}:
            continue
        if "duplicate_of=" in row["inferred_flags"]:
            continue
        slug = source.get("dso_slug", "")
        entry = totals[slug]
        horizon = _horizon(source.get("planning_horizon", ""))
        if not horizon:
            entry.unassigned_horizons += 1
            continue
        level = row["inferred_grid_level"].split(LIST_SEPARATOR)[0]
        group = RECORD_CATEGORY_GROUP.get(row["inferred_project_category"])
        if not level or not group:
            continue
        subgrid = fold(source.get("subgrid_area", ""))
        if subgrid:
            entry.names.setdefault(subgrid, str(source["subgrid_area"]).strip())
        station = level in {"EHV/HV", "HV/MV", "MV/LV"}
        quantities = {"cost": _number(source.get("reported_amount_eur", ""))}
        if station:
            quantities["mva"] = _number(source.get("capacity_change_mva", ""))
            if (
                row["inferred_record_type"] == "measure"
                and row["inferred_asset_class"] == "station"
            ):
                quantities["count"] = 1.0
        else:
            quantities["km"] = _number(source.get("line_length_km", ""))
        for quantity, value in quantities.items():
            if value is None:
                continue
            if quantity == "cost":
                value /= divisor
            entry.values[(subgrid, level, horizon, group, quantity)] += value
    return totals


def deviation_status(expected: float, actual: float, thresholds: dict) -> tuple[str, float | None]:
    """Status of one cell and the relative deviation in percent (None if undefined)."""
    if expected == 0:
        return ("pass", 0.0) if actual == 0 else ("fail", None)
    deviation = abs(actual - expected) / abs(expected)
    status = (
        "pass"
        if deviation <= thresholds["pass"]
        else ("warn" if deviation <= thresholds["warn"] else "fail")
    )
    return status, deviation * 100


def compare(
    sheets: dict[str, CompactSheet],
    totals: dict[str, Totals],
    dsos: list[str],
    config: dict,
) -> dict:
    """Compare record totals with compact sheet cells.

    Args:
        sheets: Compact sheet by DSO slug (only DSOs that have one marked).
        totals: Record totals by DSO slug.
        dsos: All DSO slugs of the run.
        config: `validation.compact_sheet` settings.

    Returns:
        metrics, deviations (non-pass cells only), unmatched subgrid areas and unassigned
        planning horizon counts, each ready for the validation report.
    """
    metrics, deviations, unmatched, unassigned = [], [], [], []
    documents = {}
    for slug in dsos:
        sheet = sheets.get(slug)
        mine = totals.get(slug, Totals())
        if mine.unassigned_horizons:
            unassigned.append(dict(dso=slug, count=mine.unassigned_horizons))
        if sheet is None:
            metrics.append(dict(name="compact_sheet", value=None, status="empty", dso=slug))
            continue
        documents[slug] = sheet.document_id
        if sheet.error:
            metrics.append(
                dict(name="compact_sheet", value=None, status="fail", dso=slug, note=sheet.error)
            )
            continue
        status, bad, uncovered = _compare_dso(slug, sheet, mine, config, deviations, unmatched)
        metrics.append(
            dict(
                name="compact_sheet",
                value=bad,
                status=status,
                dso=slug,
                document=sheet.document_id,
                uncovered_cells=uncovered,
            )
        )
    return dict(
        metrics=metrics,
        deviations=deviations,
        unmatched_subgrid_areas=unmatched,
        unassigned_planning_horizons=unassigned,
        documents=documents,
    )


def _compare_dso(slug, sheet, mine, config, deviations, unmatched) -> tuple[str, int, int]:
    named = {fold(name): name for name in sheet.subgrids}
    only_one = next(iter(named)) if len(named) == 1 else None
    record_subgrids = {key[0] for key in mine.values if key[0]}
    for key in sorted(record_subgrids - named.keys()):
        unmatched.append(dict(dso=slug, side="records", subgrid_area=mine.names[key]))
    matched = record_subgrids & named.keys()
    for key in sorted(named.keys() - record_subgrids):
        # Without any named record the subgrid column is simply unavailable.
        if record_subgrids:
            unmatched.append(dict(dso=slug, side="sheet", subgrid_area=named[key]))
    actual: dict[tuple, float] = defaultdict(float)
    # A key is covered when at least one record contributed a value to it.
    covered: set[tuple] = set()
    for (subgrid, level, horizon, group, quantity), value in mine.values.items():
        targets = ["total"]
        if subgrid in matched:
            targets.append(subgrid)
        elif not subgrid and only_one:
            targets.append(only_one)
        for target in targets:
            actual[(target, level, horizon, group, quantity)] += value
            covered.add((target, level, horizon, group, quantity))
    worst, bad, compared, uncovered = "pass", 0, 0, 0
    expected_total: dict[tuple, float | None] = {}
    for subgrid_key, cells in sheet.subgrids.items():
        for cell, value in cells.items():
            total = expected_total.setdefault(cell, 0.0)
            expected_total[cell] = None if value is None or total is None else total + value
    cells = [(fold(name), name, c, v) for name, cs in sheet.subgrids.items() for c, v in cs.items()]
    cells += [("total", "", c, v) for c, v in expected_total.items()]
    for key, label, (level, horizon, group, quantity), expected in cells:
        if key != "total" and key not in matched and key != only_one:
            continue  # no records can be placed in this area
        got = actual.get((key, level, horizon, group, quantity), 0.0)
        if expected is None:
            status, deviation = "empty", None  # missing in the sheet
        elif (
            expected
            and quantity != "count"
            and (key, level, horizon, group, quantity) not in covered
        ):
            # The sheet states a need but no record contributes to this cell: the measure
            # list does not say, so this is a coverage gap, not a deviation.
            status, deviation = "empty", None
            uncovered += 1
        else:
            status, deviation = deviation_status(expected, got, config)
            if quantity == "count" and status == "fail":
                status = "warn"  # DSOs fill the station count in by hand
        compared += status != "empty"
        if status in {"pass", "empty"}:
            continue
        bad += 1
        worst = max(worst, status, key=RANK.get)
        deviations.append(
            dict(
                dso=slug,
                subgrid_area=label or "(total)",
                grid_level=level,
                planning_horizon=horizon,
                category_group=CATEGORY_GROUPS[group],
                quantity=quantity,
                expected=expected,
                actual=got,
                deviation_percent=None if deviation is None else round(deviation, 2),
                status=status,
            )
        )
    return (worst if compared else "empty"), bad, uncovered
