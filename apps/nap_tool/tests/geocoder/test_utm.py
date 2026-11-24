# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""EPSG:25832 to latitude/longitude."""

import pytest

from nap_tool.geocoder.utm import utm32_to_wgs84

REFERENCES = [
    (810238.8552227018, 5628099.282484583, 50.72170910, 13.39588780),
    (642669.7040271858, 5837815.877706836, 52.67148088, 11.11004238),
    (538360.590499113, 5305386.37589864, 47.90065815, 9.51326411),
    (500000, 5500000, 49.65254292, 9.00000000),
    (390000, 6100000, 55.03463746, 7.27883285),
    (950000, 5900000, 53.05932307, 15.71887362),
]


@pytest.mark.parametrize(("easting", "northing", "lat", "lon"), REFERENCES)
def test_matches_reference(easting: float, northing: float, lat: float, lon: float) -> None:
    result = utm32_to_wgs84(easting, northing)
    # 1e-6 degrees is about 0.1 m; the series is accurate to millimetres here.
    assert result == pytest.approx((lat, lon), abs=1e-6)
