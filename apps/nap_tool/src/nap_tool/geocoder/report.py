# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Markdown rendering of the geocoding report."""

from __future__ import annotations

from .place_data import DATA_SOURCES_URL


def cell(value: object) -> str:
    """Text safe inside a Markdown table cell.

    Args:
        value: Cell content.

    Returns:
        The text with ``|`` escaped.
    """
    return str(value).replace("|", "\\|")


def markdown_report(report: dict) -> str:
    """Render the report of a geocoding run.

    Args:
        report: Report data from ``geocode_rows`` plus the ``place_data`` summary.

    Returns:
        Markdown text ending with a newline.
    """
    lines = [
        "# Geocoding report",
        "",
        f"Resolved: {report['resolved']} of {report['locations']} locations "
        f"({report['resolved_share']:.1%})",
        *(
            [
                f"OSM objects: {report['osm']['matched']} matched "
                f"({report['osm']['rescued']} rescued)"
            ]
            if report.get("osm_objects")
            else []
        ),
        "",
        "## By status",
        "",
        "| Status | Count |",
        "| --- | ---: |",
        *[f"| `{cell(status)}` | {count} |" for status, count in report["by_status"].items()],
        "",
        "## By kind",
        "",
        "| Kind | Total | Resolved |",
        "| --- | ---: | ---: |",
        *[
            f"| {cell(kind)} | {counts['total']} | {counts.get('resolved', 0)} |"
            for kind, counts in report["by_kind"].items()
        ],
        "",
        "## By DSO",
        "",
        "| DSO | Total | Resolved | Anchor | Anchor points |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for slug, counts in report["by_dso"].items():
        anchor = counts["anchor"]
        shown = f"{anchor[0]:.4f}, {anchor[1]:.4f}" if anchor else "—"
        lines.append(
            f"| {cell(slug)} | {counts['total']} | {counts.get('resolved', 0)} | {shown} "
            f"| {counts['anchor_points']} |"
        )
    far = report["far_from_dso"]
    lines += ["", f"## Far from DSO anchor ({len(far)})", ""]
    if far:
        lines += [
            "| Row | Role | DSO | Name | Match | km |",
            "| --- | --- | --- | --- | --- | ---: |",
        ]
        lines += [
            f"| {cell(item['row_id'])} | {item['role']} | {cell(item['dso_slug'])} "
            f"| {cell(item['name'])} | {cell(item['match'])} | {item['distance_km']} |"
            for item in far
        ]
    place_data = report["place_data"]
    lines += [
        "",
        "## Source",
        "",
        f"Place data source: {place_data['source']}, data status {place_data['data_status']}, "
        f"SHA-256 `{place_data['sha256']}`.",
        "",
        f"Place data: {place_data['attribution']} ([BKG](https://www.bkg.bund.de), "
        "[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0), "
        f"[Datenquellen]({DATA_SOURCES_URL})).",
    ]
    osm = report.get("osm_objects")
    if osm:
        lines += [
            "",
            f"OSM objects source: {osm['source']}, data status {osm['data_status']}, "
            f"SHA-256 `{osm['sha256']}`.",
            "",
            f"OSM data: {osm['attribution']}",
        ]
    return "\n".join(lines) + "\n"
