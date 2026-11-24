# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""ETRS89 / UTM zone 32N (EPSG:25832) to geographic coordinates."""

from __future__ import annotations

import math

SEMI_MAJOR_AXIS = 6378137.0  # GRS80
FLATTENING = 1 / 298.257222101
SCALE = 0.9996
FALSE_EASTING = 500000.0
CENTRAL_MERIDIAN = 9.0  # zone 32

_N = FLATTENING / (2 - FLATTENING)
_A = SEMI_MAJOR_AXIS / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_BETA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96,
    _N**2 / 48 + _N**3 / 15,
    17 * _N**3 / 480,
)
_DELTA = (
    2 * _N - 2 * _N**2 / 3 - 2 * _N**3,
    7 * _N**2 / 3 - 8 * _N**3 / 5,
    56 * _N**3 / 15,
)


def utm32_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert an EPSG:25832 coordinate to latitude and longitude (Krüger series).

    ETRS89 and WGS84 differ by well under a metre in Germany, far below the precision
    of a settlement point.

    Args:
        easting: UTM easting in metres, without zone prefix.
        northing: UTM northing in metres (northern hemisphere).

    Returns:
        Latitude and longitude in decimal degrees.
    """
    xi = northing / (SCALE * _A)
    eta = (easting - FALSE_EASTING) / (SCALE * _A)
    xi_prime = xi - sum(
        beta * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        for j, beta in enumerate(_BETA, start=1)
    )
    eta_prime = eta - sum(
        beta * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
        for j, beta in enumerate(_BETA, start=1)
    )
    chi = math.asin(math.sin(xi_prime) / math.cosh(eta_prime))
    latitude = chi + sum(delta * math.sin(2 * j * chi) for j, delta in enumerate(_DELTA, start=1))
    longitude = math.radians(CENTRAL_MERIDIAN) + math.atan2(
        math.sinh(eta_prime), math.cos(xi_prime)
    )
    return math.degrees(latitude), math.degrees(longitude)
