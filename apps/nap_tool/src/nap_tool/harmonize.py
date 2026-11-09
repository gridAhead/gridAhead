# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Deterministic grouping and merging for harmonization schemes."""

from __future__ import annotations

import csv
import io
import re
import unicodedata


def normalize_header(value: str) -> str:
    """Normalize a header for comparison without changing its stored spelling.

    Args:
        value: Original column name.

    Returns:
        Comparison form.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def lcs_rate(first: str, second: str) -> float:
    """Return symmetric longest-common-subsequence similarity.

    Args:
        first: First normalized header.
        second: Second normalized header.

    Returns:
        Similarity from zero to one.
    """
    if not first or not second:
        return float(first == second)
    masks: dict[str, int] = {}
    for index, character in enumerate(second):
        masks[character] = masks.get(character, 0) | (1 << index)
    state = 0
    for character in first:
        matches = masks.get(character, 0) | state
        state = matches & ~(matches - ((state << 1) | 1))
    return 2 * state.bit_count() / (len(first) + len(second))


def group_headers(names: list[str], threshold: float) -> list[list[str]]:
    """Group names only when each pair passes the LCS threshold.

    Args:
        names: Headers ordered by frequency, then spelling.
        threshold: Minimum similarity.

    Returns:
        Stable groups of original names.
    """
    normalized = {name: normalize_header(name) for name in names}
    groups: list[list[str]] = []
    for name in names:
        for group in groups:
            if all(lcs_rate(normalized[name], normalized[member]) >= threshold for member in group):
                group.append(name)
                break
        else:
            groups.append([name])
    return groups


def field_key(name: str) -> str:
    """Create a stable, readable key for a proposed target field.

    Args:
        name: Target field name.

    Returns:
        Identifier suitable for scheme JSON.
    """
    substitutions = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
    normalized = unicodedata.normalize("NFKD", name.casefold().translate(substitutions))
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_") or "feld"


def csv_rows(content: bytes) -> list[list[str]]:
    """Decode a source CSV, preserving the original column positions.

    Args:
        content: UTF-8 CSV bytes.

    Returns:
        Parsed rows.
    """
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def csv_content(rows: list[list[str]]) -> bytes:
    """Encode harmonized rows as a portable CSV.

    Args:
        rows: Header and data rows.

    Returns:
        UTF-8 CSV bytes.
    """
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue().encode("utf-8")
