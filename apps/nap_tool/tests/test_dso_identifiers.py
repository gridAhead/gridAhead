# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Official identifier matching keeps BDEW market roles separate."""

from nap_tool import dso_identifiers


def test_bdew_match_uses_only_unique_network_operator_code(monkeypatch) -> None:
    def fake_json(_url, _data):
        return {
            "Result": "OK",
            "Records": [
                {"BdewCode": "9900000000001", "MarketFunctionName": "Lieferant"},
                {"BdewCode": "9907137000005", "MarketFunctionName": "Netzbetreiber"},
            ],
        }

    monkeypatch.setattr(dso_identifiers, "_json", fake_json)
    assert dso_identifiers._network_operator_code(123) == "9907137000005"


def test_verified_name_variants_and_same_name_companies() -> None:
    assert dso_identifiers._name("Celle-Uelzen Netz GmbH") == dso_identifiers._name("SVO Netz GmbH")
    assert dso_identifiers._company_id("SWE Netz GmbH (Erfurt)", {}) == 2570
    assert dso_identifiers._name("SWE Netz GmbH (Ettlingen)") != dso_identifiers._name(
        "SWE Netz GmbH (Erfurt)"
    )
