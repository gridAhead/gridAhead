# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""One normalization for place data names and NAP location names."""

from __future__ import annotations

import re
import unicodedata

SAINT_RE = re.compile(r"\b(?:st\.|sankt\b)\s*")
PUNCTUATION_RE = re.compile(r"[-‐‑–—/_.,;:()\[\]\"'„“”‚‘’]+")
# Trailing qualifier of a settlement name: '(Müritz)', '/Mark', 'a.d. Waldnaab', 'am Main'.
QUALIFIER_RE = re.compile(
    r"\s*\([^)]*\)\s*$|\s*/\s*\S.*$|"
    r"\s+(?:(?:a\.\s?d\.|a\.|b\.|i\.)\s*"
    r"|(?:bei|am|an der|an den|im|in|in der|auf|ob der|vor der)\s+)\S.*$",
    re.I,
)


def normalize(name: str) -> str:
    """Comparable form of a place name.

    NFKC, casefold (which turns 'ß' into 'ss'), 'St.' and 'Sankt' unified, punctuation
    and hyphens turned into spaces, whitespace collapsed.

    Args:
        name: Place name as written.

    Returns:
        Normalized name; empty for a name without letters or digits.
    """
    text = unicodedata.normalize("NFKC", name).casefold()
    text = SAINT_RE.sub("sankt ", text)
    text = PUNCTUATION_RE.sub(" ", text)
    return " ".join(text.split())


def without_qualifier(name: str) -> str | None:
    """Name without its trailing qualifier ('Waren (Müritz)' -> 'Waren').

    Args:
        name: Place name as written.

    Returns:
        The shorter name, or None when the name has no qualifier.
    """
    stripped = QUALIFIER_RE.sub("", name).strip()
    return stripped if stripped and stripped != name.strip() else None
