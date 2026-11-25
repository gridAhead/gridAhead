# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Location proposals: their line format, input hash, evidence check and application.

Claude proposes, code decides (ADR-0002, ADR-0008): a proposal only fills empty location
columns, deterministically and flagged, and only while its record's source text is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .rules import LIST_SEPARATOR

SourceField = Literal["measure_name", "measure_description", "upstream_grid_node"]
# The reading-package source fields; never stage-1 values, so a rule change keeps a
# proposal non-stale and a changed source cell makes it stale.
SOURCE_FIELDS = get_args(SourceField)
LLM_PROPOSAL_FLAG = "location_source:llm_proposal"
ROLE_COLUMNS = {
    "start": "inferred_location_start",
    "site": "inferred_location_start",
    "area": "inferred_location_start",
    "end": "inferred_location_end",
    "via": "inferred_location_via",
}
KIND_COLUMNS = {
    "inferred_location_start": "inferred_location_start_kind",
    "inferred_location_end": "inferred_location_end_kind",
}
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Evidence(BaseModel):
    """A verbatim quote from one source field of the record."""

    model_config = ConfigDict(extra="forbid")
    field: SourceField
    quote: Text


class ProposedLocation(BaseModel):
    """One proposed location of a record."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["start", "end", "via", "site", "area"]
    name: Text
    kind: Literal[
        "substation",
        "switching_station",
        "local_substation",
        "search_area",
        "street_address",
        "code",
        "place",
    ]
    evidence: Evidence
    candidate: Text | None = None


class ProposalLine(BaseModel):
    """One proposal line as read by `nap-tool propose add`."""

    model_config = ConfigDict(extra="forbid")
    row_id: Text
    locations: list[ProposedLocation] = Field(min_length=1)


def row_id(record: dict[str, str]) -> str:
    """Return a harmonized record's row id, `<extract table>-<row number>`.

    Args:
        record: Harmonized record with its `source_cells_json` provenance.

    Returns:
        The row id, as `classify` writes it.

    Raises:
        ValueError: If the provenance is malformed.
    """
    try:
        origin = json.loads(record["source_cells_json"])["origin"]
        return f"{origin['extract_table_id']}-{origin['row_number']}"
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid source_cells_json: {error}") from error


def input_sha256(record: dict[str, str]) -> str:
    """Hash the reading-package source fields of a record.

    Args:
        record: Record with stable field keys.

    Returns:
        Hex sha256 over the source fields, in SOURCE_FIELDS order.
    """
    values = [record.get(field, "") for field in SOURCE_FIELDS]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def quote_error(record: dict[str, str], proposal: ProposalLine) -> str | None:
    """Check that every location quotes its named source field verbatim.

    Whitespace and case are normalized on both sides.

    Args:
        record: Record with stable field keys.
        proposal: Proposal for the record.

    Returns:
        The reason of the first failing quote, or None if all quotes are found.
    """
    for location in proposal.locations:
        field, quote = location.evidence.field, location.evidence.quote
        if _normalized(quote) not in _normalized(record.get(field, "")):
            return f"quote {quote!r} not found in {field}"
    return None


def apply_proposal(
    record: dict[str, str], out: dict[str, str], flags: set[str], proposals: list[dict]
) -> set[str]:
    """Fill empty location columns from the newest non-stale proposal of a measure.

    The proposal applies only if every location it proposes fills an empty stage-1
    column; otherwise the stage-1 result stays unchanged.

    Args:
        record: Record with stable field keys.
        out: Derived values; the location columns are filled in place.
        flags: Flags of the record after stage 1.
        proposals: Proposed proposals of the record, oldest first, each with
            `input_sha256` and `locations` (`role`, `name`, `kind`).

    Returns:
        The record's flags, with `location_source:llm_proposal` if the proposal applied.
    """
    if "refers_to_other_measure" in flags:
        return flags
    digest = input_sha256(record)
    non_stale = [proposal for proposal in proposals if proposal["input_sha256"] == digest]
    if not non_stale:
        return flags
    columns: dict[str, list[dict]] = {}
    for location in non_stale[-1]["locations"]:
        columns.setdefault(ROLE_COLUMNS[location["role"]], []).append(location)
    if any(out[column] for column in columns):
        return flags
    for column, locations in columns.items():
        out[column] = LIST_SEPARATOR.join(location["name"] for location in locations)
        if column in KIND_COLUMNS:
            out[KIND_COLUMNS[column]] = locations[0]["kind"]
    flags = flags | {LLM_PROPOSAL_FLAG}
    if out["inferred_location_start"]:
        flags.discard("location_missing")
    if out["inferred_location_end"]:
        flags.discard("location_end_missing")
    elif out["inferred_asset_class"] == "line" and out["inferred_location_start"]:
        flags.add("location_end_missing")
    return flags
