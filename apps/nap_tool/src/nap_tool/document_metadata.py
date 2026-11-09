# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Normalize legacy document metadata when importing documents or upgrading a repository."""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo


def infer_nap_year(title: str, version: str | None) -> int | None:
    """Use the NAP year in metadata or title, then the Berlin version date."""
    metadata: object = None
    if version:
        try:
            metadata = json.loads(version)
        except json.JSONDecodeError:
            metadata = version
    if isinstance(metadata, dict):
        if metadata.get("nap_year_is_manual") is True and metadata.get("nap_year") is None:
            return None
        nap_year = metadata.get("nap_year")
        if (
            isinstance(nap_year, (int, str))
            and re.fullmatch(r"\d{4}", str(nap_year))
            and 2000 <= int(nap_year) <= 2100
        ):
            return int(nap_year)

    version_year = None
    current_from = metadata.get("current_from") if isinstance(metadata, dict) else metadata
    if isinstance(current_from, str) and current_from:
        try:
            version_year = (
                datetime.fromisoformat(current_from).astimezone(ZoneInfo("Europe/Berlin")).year
            )
        except ValueError:
            match = re.fullmatch(r"20\d{2}", current_from)
            if match:
                version_year = int(current_from)

    title_years = [int(year) for year in re.findall(r"(?<!\d)20\d{2}(?!\d)", title)]
    if title_years:
        plausible = [year for year in title_years if version_year is None or year <= version_year]
        if plausible:
            return min(plausible)
    return version_year


def version_dates(version: str | None) -> tuple[str | None, str | None]:
    """Extract plain source version and expiry dates from legacy JSON."""
    try:
        metadata = json.loads(version) if version else None
    except json.JSONDecodeError:
        return version, None
    if isinstance(metadata, dict):
        start, end = metadata.get("current_from"), metadata.get("current_to")
        return (str(start) if start is not None else None, str(end) if end is not None else None)
    return version, None
