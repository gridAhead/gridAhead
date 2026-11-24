# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Name normalization shared by place data and NAP names."""

import pytest

from nap_tool.geocoder.normalize import normalize, without_qualifier


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("St. Peter", "sankt peter"),
        ("Sankt Peter", "sankt peter"),
        ("Großenhain", "grossenhain"),
        ("Königstein/Sächs.Schw.", "königstein sächs schw"),
        ("  Bad   Muster-Dorf ", "bad muster dorf"),
        ("Waren (Müritz)", "waren müritz"),
    ],
)
def test_normalize(name: str, expected: str) -> None:
    assert normalize(name) == expected


def test_normalize_is_idempotent() -> None:
    assert normalize(normalize("St. Peter-Ording")) == normalize("St. Peter-Ording")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Waren (Müritz)", "Waren"),
        ("Dannenberg/Mark", "Dannenberg"),
        ("Königstein/Sächs.Schw.", "Königstein"),
        ("Altenstadt a.d.Waldnaab", "Altenstadt"),
        ("Neunkirchen a.Sand", "Neunkirchen"),
        ("Schwarzach bei Kulmbach", "Schwarzach"),
        ("Frankfurt am Main", "Frankfurt"),
        ("Musterdorf", None),
        ("Am Berg", None),
        ("Groß Ammensleben", None),
        ("Bad Imnau", None),
        ("Groß Beiersdorf", None),
        ("Bad Ambach", None),
        ("Neustadt in Holstein", "Neustadt"),
        ("Burg auf Fehmarn", "Burg"),
    ],
)
def test_without_qualifier(name: str, expected: str | None) -> None:
    assert without_qualifier(name) == expected
