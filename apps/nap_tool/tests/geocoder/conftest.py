# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""A small archive in GN250's CSV format."""

import io
import zipfile
from typing import Callable

import pytest

GN250_HEADER = (
    "NNID;DATUM;OBA;OBA_WERT;NAME;SPRACHE;GENUS;NAME2;SPRACHE2;GENUS2;ZUSATZ;AGS;ARS;HOEHE;"
    "HOEHE_GER;EWZ;EWZ_GER;GEWK;GEMTEIL;VIRTUELL;GEMEINDE;VERWGEM;KREIS;REGBEZIRK;BUNDESLAND;"
    "STAAT;RECHTS;HOCH;BOX"
)
BOM = bytes([0xEF, 0xBB, 0xBF])  # UTF-8 byte order mark
PLACES = [
    {
        "NNID": "DEBKGGND00000001",
        "OBA": "AX_Ortslage",
        "NAME": "Musterdorf",
        "AGS": "14522001",
        "EWZ_GER": "500",
        "RECHTS": "810238.8552227018",
        "HOCH": "5628099.282484583",
    },
    {
        "NNID": "DEBKGGND00000002",
        "OBA": "AX_Gemeinde",
        "NAME": "Beispielstadt",
        "AGS": "14522002",
        "EWZ": "9000",
        "RECHTS": "815000",
        "HOCH": "5630000",
    },
    {
        "NNID": "DEBKGGND00000003",
        "OBA": "AX_Ortslage",
        "NAME": "Probstheim",
        "AGS": "14522003",
        "EWZ_GER": "300",
        "RECHTS": "805000",
        "HOCH": "5625000",
    },
    {
        "NNID": "DEBKGGND00000004",
        "OBA": "AX_Ortslage",
        "NAME": "Kirchberg",
        "AGS": "14522004",
        "EWZ_GER": "700",
        "RECHTS": "812000",
        "HOCH": "5626000",
    },
    {
        "NNID": "DEBKGGND00000005",
        "OBA": "AX_Ortslage",
        "NAME": "Kirchberg",
        "AGS": "06000001",
        "EWZ_GER": "900",
        "RECHTS": "500000",
        "HOCH": "5500000",
    },
    {
        "NNID": "DEBKGGND00000006",
        "OBA": "Gewaesser",
        "NAME": "Musterbach",
        "RECHTS": "811000",
        "HOCH": "5627000",
    },
]


def gn250_archive(records: list[dict[str, str]], header: str = GN250_HEADER) -> bytes:
    """ZIP bytes laid out like the BKG download: BOM, ';', CRLF."""
    columns = header.split(";")
    lines = [header, *(";".join(record.get(c, "") for c in columns) for record in records)]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("gn250/GN250.csv", BOM + ("\r\n".join(lines) + "\r\n").encode())
        archive.writestr("dokumentation/aktualitaet.txt", "31.12.2024")
    return buffer.getvalue()


@pytest.fixture
def make_archive() -> Callable[..., bytes]:
    return gn250_archive


@pytest.fixture
def archive() -> bytes:
    return gn250_archive(PLACES)
