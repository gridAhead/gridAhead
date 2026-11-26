# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""A temporary data repository with one harmonized grid-measure row."""

import csv
import json

import pytest

from nap_tool.classifier.config import load_config
from nap_tool.data import sha256_file
from nap_tool.database.schema import connect


@pytest.fixture
def repository(tmp_path):
    config = load_config()
    headers = list(config.required_fields)
    # Verify display titles can be mapped to stable keys without changing the original CSV.
    headers[headers.index("measure_name")] = "Maßnahme"
    values = dict.fromkeys(headers, "")
    values.update(
        dso_slug="test",
        measure_description="Kabelneubau",
        **{"Maßnahme": "Neubau 20 kV Kabel"},
    )
    values["source_cells_json"] = json.dumps(
        {
            "origin": {
                "extract_table_id": 1,
                "row_number": 2,
                "document_id": 1,
                "currentFrom": "2024-04-01",
                "clean_is_confirmed": True,
            },
            "sources": [],
        }
    )
    path = tmp_path / "harmonized/scheme_1/output.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, headers)
        writer.writeheader()
        writer.writerow(values)
    with connect(tmp_path / "nap_tool.sqlite") as db:
        db.execute(
            "INSERT INTO dso(name,slug,mastr_nr,bdew_code,created_at,updated_at) "
            "VALUES ('Test','test','ABC','123','now','now')"
        )
        db.execute(
            "INSERT INTO harmonize_set(id,name,slug,table_type_id,created_at) "
            "VALUES (1,'Test','test',1,'now')"
        )
        db.execute(
            "INSERT INTO harmonize_scheme(id,name,initial_set_id,created_at,updated_at) "
            "VALUES (1,'Test',1,'now','now')"
        )
        db.execute(
            "INSERT INTO harmonize_field(scheme_id,field_key,title,position,created_at,updated_at) "
            "VALUES (1,'measure_name','Maßnahme',1,'now','now')"
        )
        from nap_tool.ui.harmonize_api import _fields, _pair_manifest, _pair_tables

        scheme = db.execute("SELECT * FROM harmonize_scheme WHERE id=1").fetchone()
        tables = _pair_tables(db, tmp_path, scheme, 1)
        manifest = _pair_manifest(_fields(db, scheme, tables), tables)
        db.execute(
            "INSERT INTO harmonize_set_output VALUES (1,1,?,?,?,'now')",
            (str(path.relative_to(tmp_path)), sha256_file(path), manifest),
        )
    return tmp_path, path, values
