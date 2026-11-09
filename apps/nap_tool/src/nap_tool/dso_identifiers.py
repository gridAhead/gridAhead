# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Match DSO identifiers against the public MaStR and BDEW registries."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nap_tool.database.schema import connect

MASTR_URL = (
    "https://www.marktstammdatenregister.de/MaStR/Akteur/"
    "MarktakteurJson/GetOeffentlicheMarktakteure"
)
BDEW_BASE = "https://bdew-codes.de/Codenumbers/BDEWCodes"
HEADERS = {"User-Agent": "NAP Tool (public registry lookup)"}
# The company announced that Celle-Uelzen Netz GmbH became SVO Netz GmbH
# on 18 September 2026; its MaStR and BDEW records now use the new name.
# https://www.svo-netz.de/
RENAMED_DSOS = {"celleuelzennetzgmbh": "svonetzgmbh"}
# BDEW lists two companies as "SWE Netz GmbH". MaStR's Erfurt role MP-ID
# matches the Netzbetreiber code of BDEW company 2570, not 2571 (Ettlingen).
# https://www.marktstammdatenregister.de/MaStR/Akteur/Marktakteur/DetailOeffentlich/1001524
VERIFIED_BDEW_COMPANIES = {"swenetzgmbherfurt": (2570, "9900744000004")}


def _json(url: str, data: dict[str, object] | None = None) -> dict[str, object]:
    body = urlencode(data).encode() if data is not None else None
    with urlopen(Request(url, data=body, headers=HEADERS), timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError(f"Registry returned an invalid response: {url}")
    return result


def _name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s*\([A-Z]{2,5}\)$", "", value)
    key = "".join(character for character in value.casefold() if character.isalnum())
    return RENAMED_DSOS.get(key, key)


def _unique_by_name(rows: list[dict[str, object]], name_key: str) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        name = row.get(name_key)
        if isinstance(name, str) and name.strip():
            grouped[_name(name)].append(row)
    return {name: matches[0] for name, matches in grouped.items() if len(matches) == 1}


def _mastr_actors() -> dict[str, dict[str, object]]:
    params = urlencode(
        {
            "page": 1,
            "pageSize": 5000,
            "skip": 0,
            "take": 5000,
            "filter": "Marktfunktion~eq~'Stromnetzbetreiber'",
        }
    )
    response = _json(f"{MASTR_URL}?{params}")
    rows = response.get("Data")
    if not isinstance(rows, list) or len(rows) != response.get("Total"):
        raise ValueError("MaStR electricity operator listing is incomplete")
    return _unique_by_name(
        [row for row in rows if isinstance(row, dict) and row.get("TaetigkeitsStatus") == "Aktiv"],
        "NameConcealed",
    )


def _bdew_companies() -> dict[str, dict[str, object]]:
    response = _json(f"{BDEW_BASE}/GetCompanyList", {"jtStartIndex": 0, "jtPageSize": 10000})
    rows = response.get("Records")
    if (
        response.get("Result") != "OK"
        or not isinstance(rows, list)
        or len(rows) != response.get("TotalRecordCount")
    ):
        raise ValueError("BDEW company listing is incomplete")
    return _unique_by_name([row for row in rows if isinstance(row, dict)], "Company")


def _network_operator_code(company_id: int) -> str | None:
    response = _json(
        f"{BDEW_BASE}/GetBdewCodeListOfCompany?companyId={company_id}&filter=",
        {"jtStartIndex": 0, "jtPageSize": 100},
    )
    rows = response.get("Records")
    if response.get("Result") != "OK" or not isinstance(rows, list):
        raise ValueError(f"BDEW codes unavailable for company {company_id}")
    matches = {
        row.get("BdewCode")
        for row in rows
        if isinstance(row, dict)
        and row.get("MarketFunctionName") == "Netzbetreiber"
        and isinstance(row.get("BdewCode"), str)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _company_id(name: str, companies: dict[str, dict[str, object]]) -> int | None:
    key = _name(name)
    if key in VERIFIED_BDEW_COMPANIES:
        return VERIFIED_BDEW_COMPANIES[key][0]
    company = companies.get(key)
    return int(company["Id"]) if company else None


def sync_dso_identifiers(database: Path) -> dict[str, int]:
    """Fill only empty identifiers that have unique official name and role matches."""
    with connect(database) as connection:
        dsos = [
            dict(row) for row in connection.execute("SELECT id, name, mastr_nr, bdew_code FROM dso")
        ]
    actors = _mastr_actors()
    companies = _bdew_companies()
    company_ids = {
        company_id
        for dso in dsos
        if not dso["bdew_code"]
        if (company_id := _company_id(dso["name"], companies)) is not None
    }
    codes: dict[int, str | None] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_network_operator_code, company_id): company_id
            for company_id in company_ids
        }
        for future in as_completed(futures):
            codes[futures[future]] = future.result()

    result = {"mastr_matched": 0, "bdew_matched": 0, "unmatched": 0}
    with connect(database) as connection:
        for dso in dsos:
            key = _name(dso["name"])
            actor = actors.get(key)
            mastr = actor.get("MaStRNummer") if actor else None
            if not (isinstance(mastr, str) and mastr.startswith("SNB")):
                mastr = None
            company_id = _company_id(dso["name"], companies)
            bdew = codes.get(company_id) if company_id else None
            verified = VERIFIED_BDEW_COMPANIES.get(key)
            if verified and bdew != verified[1]:
                bdew = None
            if mastr and not dso["mastr_nr"]:
                connection.execute(
                    "UPDATE dso SET mastr_nr=? WHERE id=? AND COALESCE(mastr_nr, '')=''",
                    (mastr, dso["id"]),
                )
                result["mastr_matched"] += 1
            if bdew and not dso["bdew_code"]:
                connection.execute(
                    "UPDATE dso SET bdew_code=? WHERE id=? AND COALESCE(bdew_code, '')=''",
                    (bdew, dso["id"]),
                )
                result["bdew_matched"] += 1
            if not (mastr or dso["mastr_nr"]) or not (bdew or dso["bdew_code"]):
                result["unmatched"] += 1
    return result
