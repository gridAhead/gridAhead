# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Public report content assembled from derived rows and provenance."""

from __future__ import annotations

from collections import Counter, defaultdict

from . import compact_sheet as compact
from .config import ClassifyConfig
from .rules import LIST_SEPARATOR, NORMALIZED_FIELDS


def with_metric_expectations(report: dict, validation: dict) -> dict:
    """Add the configured pass criteria without changing metric values or statuses.

    Args:
        report: Validation report, including reports saved before criteria were recorded.
        validation: Validation settings used to determine the expected values.

    Returns:
        A report with expected values attached to each metric.
    """

    def expected_value(name: str) -> str:
        if name == "dso_count":
            low, high = validation["dso_count"]["pass"]
            return f"{low}–{high}"
        group = name.partition(":")[0]
        if group in {"measure_share", "vocabulary", "coverage"}:
            return f"≥ {validation[group]['pass']:g}"
        if name == "compact_sheet":
            limits = validation.get("compact_sheet")
            return f"≤ {limits['pass']:.0%}" if limits else ""
        if name in {"unflagged_duplicates", "documents_outside_round", "unconfirmed_cleaning"}:
            return "0"
        return ""

    return {
        **report,
        "metrics": [
            {**item, "expected": item.get("expected", expected_value(item["name"]))}
            for item in report["metrics"]
        ],
    }


def validate(
    rows: list[dict[str, str]],
    inputs: list[dict[str, str]],
    origins: list[dict],
    config: ClassifyConfig,
    unresolved: list[dict],
    compact_sheets: dict[str, compact.CompactSheet] | None = None,
) -> dict:
    metrics = []

    def metric(name: str, value: float | int | None, status: str, dso: str = "") -> None:
        metrics.append(dict(name=name, value=value, status=status, dso=dso))

    def coverage(
        name: str, numerator: int, denominator: int, thresholds: dict, dso: str = ""
    ) -> None:
        # Nothing to rate (0/0) is reported as empty: neither pass nor fail.
        if not denominator:
            metric(name, None, "empty", dso)
            return
        ratio = numerator / denominator
        status = (
            "pass"
            if ratio >= thresholds["pass"]
            else ("warn" if ratio >= thresholds["warn"] else "fail")
        )
        metric(name, ratio, status, dso)

    def vocabulary(field: str, indices: list[int], dso: str = "") -> None:
        nonempty = [i for i in indices if inputs[i].get(field)]
        coverage(
            f"vocabulary:{field}",
            sum(
                f"unmapped:{field}" not in rows[i]["inferred_flags"].split(LIST_SEPARATOR)
                for i in nonempty
            ),
            len(nonempty),
            config.validation["vocabulary"],
            dso,
        )
        # Informational only: shows how much of the field is unfilled, without a status.
        empty = len(indices) - len(nonempty)
        metrics[-1].update(
            empty_count=empty,
            row_count=len(indices),
            empty_share=empty / len(indices) if indices else None,
        )

    dsos = sorted({row.get("dso_slug", "") for row in inputs})
    low, high = config.validation["dso_count"]["pass"]
    warn_low, warn_high = config.validation["dso_count"]["warn"]
    metric(
        "dso_count",
        len(dsos),
        "pass"
        if low <= len(dsos) <= high
        else ("warn" if warn_low <= len(dsos) <= warn_high else "fail"),
    )
    measures = [row for row in rows if row["inferred_record_type"] == "measure"]
    coverage("measure_share", len(measures), len(rows), config.validation["measure_share"])
    for field in NORMALIZED_FIELDS:
        vocabulary(field, list(range(len(inputs))))
    for slug in dsos:
        indices = [i for i, source in enumerate(inputs) if source.get("dso_slug", "") == slug]
        coverage(
            "measure_share",
            sum(rows[i]["inferred_record_type"] == "measure" for i in indices),
            len(indices),
            config.validation["measure_share"],
            slug,
        )
        for field in NORMALIZED_FIELDS:
            vocabulary(field, indices, slug)
        selected = [
            rows[i]
            for i, source in enumerate(inputs)
            if source.get("dso_slug", "") == slug and rows[i]["inferred_record_type"] == "measure"
        ]
        for field in ["inferred_asset_type", "inferred_grid_level", "inferred_measure_type"]:
            coverage(
                f"coverage:{field}",
                sum(bool(row[field]) for row in selected),
                len(selected),
                config.validation["coverage"],
                slug,
            )
    seen = set()
    unflagged = 0
    repeated = defaultdict(list)
    repeated_sources = defaultdict(list)
    for row, source, origin in zip(rows, inputs, origins):
        identity = tuple(
            (key, value) for key, value in sorted(source.items()) if key != "source_cells_json"
        )
        if identity in seen and "duplicate_of=" not in row["inferred_flags"]:
            unflagged += 1
        seen.add(identity)
        if source.get("measure_no"):
            key = (source.get("dso_slug", ""), source["measure_no"])
            repeated[key].append(row["row_id"])
            repeated_sources[key].append(
                dict(
                    row_id=row["row_id"],
                    document=origin.get("document_id"),
                    extract_table_id=origin["extract_table_id"],
                    table_number=origin.get("table_number"),
                    row_number=origin["row_number"],
                )
            )
    metric("unflagged_duplicates", unflagged, "fail" if unflagged else "pass")
    outside = [
        row["row_id"]
        for row in rows
        if "document_outside_round" in row["inferred_flags"].split(LIST_SEPARATOR)
    ]
    metric("documents_outside_round", len(outside), "warn" if outside else "pass")
    unconfirmed = sum(origin.get("clean_is_confirmed") is False for origin in origins)
    metric(
        "unconfirmed_cleaning",
        unconfirmed / len(rows) if rows else 0,
        "warn" if unconfirmed else "pass",
    )
    check = None
    settings = config.validation.get("compact_sheet")
    if settings and compact_sheets is not None:
        check = compact.compare(
            compact_sheets,
            compact.record_totals(rows, inputs, settings),
            dsos,
            settings,
        )
        metrics.extend(check["metrics"])
    rank = {"pass": 0, "warn": 1, "fail": 2}
    status = max(
        (item["status"] for item in metrics if item["status"] != "empty"),
        key=rank.get,
        default="pass",
    )
    report = {
        "status": status,
        "rows": len(rows),
        "nap_round": config.round.year,
        "metrics": metrics,
        "record_types": dict(sorted(Counter(row["inferred_record_type"] for row in rows).items())),
        "flag_counts": dict(
            sorted(
                Counter(
                    flag
                    for row in rows
                    for flag in row["inferred_flags"].split(LIST_SEPARATOR)
                    if flag
                ).items()
            )
        ),
        "quality": {
            key: dict(sorted(Counter(row[key] for row in measures).items()))
            for key in ["inferred_quality_classification", "inferred_quality_location"]
        },
        "coverage": {
            key: sum(bool(row[key]) for row in measures) / len(measures) if measures else 0
            for key in [
                "inferred_asset_type",
                "inferred_grid_level",
                "inferred_measure_type",
                "inferred_voltage",
                "inferred_line_capacity_change_mva",
                "inferred_station_capacity_change_mva",
                "inferred_location_start",
                "inferred_location_end",
            ]
        },
        "unresolved_values": unresolved,
        "repeated_measure_numbers": [
            dict(dso=key[0], measure_no=key[1], row_ids=value, sources=repeated_sources[key])
            for key, value in sorted(repeated.items())
            if len(value) > 1
        ],
        "dsos_without_codes": sorted(
            {
                inputs[i].get("dso_slug", "")
                for i, row in enumerate(rows)
                if not row["dso_mastr_nr"] or not row["dso_bdew_code"]
            }
        ),
        "rows_without_document_date": [row["row_id"] for row in rows if not row["document_date"]],
        "documents_outside_round": outside,
    }
    if check is not None:
        report["compact_sheet_deviations"] = check["deviations"]
        report["unmatched_subgrid_areas"] = check["unmatched_subgrid_areas"]
        report["unassigned_planning_horizons"] = check["unassigned_planning_horizons"]
        report["compact_sheet_documents"] = check["documents"]
    return with_metric_expectations(report, config.validation)


def empty_share(item: dict) -> str:
    """Format a metric's empty-cell share with its counts.

    Args:
        item: Report metric; only vocabulary metrics carry empty-cell counts.

    Returns:
        Text such as "24.0% (50/208)", or "—" when the metric has no counts.
    """
    if item.get("empty_share") is None:
        return "—"
    return f"{item['empty_share']:.1%} ({item['empty_count']}/{item['row_count']})"


def markdown_report(report: dict) -> str:
    import json

    lines = [
        "# Classification validation",
        "",
        f"Overall: **{report['status']}**",
        f"Rows: {report['rows']}",
        "",
        "| Metric | DSO | Value | Empty share | Expected value (pass criteria) | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["metrics"]:
        value = "-" if item["value"] is None else f"{item['value']:.4g}"
        lines.append(
            f"| {item['name']} | {item['dso']} | {value} | {empty_share(item)} "
            f"| {item.get('expected', '—')} | {item['status']} |"
        )
    for key in [
        "record_types",
        "flag_counts",
        "quality",
        "coverage",
        "dropped_rows",
        "unresolved_values",
        "repeated_measure_numbers",
        "dsos_without_codes",
        "rows_without_document_date",
        "documents_outside_round",
        "compact_sheet_deviations",
        "unmatched_subgrid_areas",
        "unassigned_planning_horizons",
    ]:
        if key not in report:  # reports saved before the key existed
            continue
        lines.extend(
            [
                "",
                f"## {key}",
                "",
                "```json",
                json.dumps(report[key], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"
