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
import math
import random
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .rules import LIST_SEPARATOR

SourceField = Literal["measure_name", "measure_description", "upstream_grid_node"]
# The reading-package source fields; never stage-1 values, so a rule change keeps a
# proposal non-stale and a changed source cell makes it stale.
SOURCE_FIELDS = get_args(SourceField)
LLM_PROPOSAL_FLAG = "location_source:llm_proposal"
# Marks a human-accepted proposal, whose location quality is not capped at medium.
REVIEWED_PROPOSAL_FLAG = "llm_proposal_reviewed"
CONFLICT_FLAG = "llm_proposal_conflict"
# Flags describing how stage 1 derived its locations, void once a reviewer overrules them;
# matched with startswith, so `location_source:` covers every source.
STAGE1_LOCATION_FLAGS = (
    "location_source:",
    "location_hyphen_split",
    "location_route_split",
    "location_multiple",
)
ROLE_COLUMNS = {
    "start": "inferred_location_start",
    "site": "inferred_location_start",
    "area": "inferred_location_start",
    "end": "inferred_location_end",
    "via": "inferred_location_via",
}
# Stage-1 location columns by their label in the review CSV: start, end, via.
STAGE1_LOCATIONS = {
    column.removeprefix("inferred_location_"): column for column in ROLE_COLUMNS.values()
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


def proposed_columns(out: dict[str, str], proposal: dict) -> dict[str, list[dict]]:
    """Group a proposal's locations by the location column they fill.

    A column whose stage-1 value the proposal repeats (same names after whitespace and
    case normalization) is left out: the proposal confirms it and changes nothing there.

    Args:
        out: Derived values of the record after stage 1.
        proposal: Proposal with `locations` (`role`, `name`, `kind`).

    Returns:
        The locations of each column the proposal would change, in submission order.
    """
    columns: dict[str, list[dict]] = {}
    for location in proposal["locations"]:
        columns.setdefault(ROLE_COLUMNS[location["role"]], []).append(location)
    return {
        column: locations
        for column, locations in columns.items()
        if [_normalized(location["name"]) for location in locations]
        != [_normalized(name) for name in out[column].split(LIST_SEPARATOR) if name.strip()]
    }


def replaces_stage1_location(out: dict[str, str], proposal: dict) -> bool:
    """Tell whether a proposal would replace a stage-1 location with a different one.

    Args:
        out: Derived values of the record after stage 1.
        proposal: Proposal with `locations` (`role`, `name`, `kind`).

    Returns:
        True if a column the proposal would change already has a stage-1 value.
    """
    return any(out[column] for column in proposed_columns(out, proposal))


def pick_proposals(
    record: dict[str, str], out: dict[str, str], flags: set[str], proposals: list[dict]
) -> tuple[dict | None, list[dict]]:
    """Return the proposal `classify` applies to a record and its unreviewed conflicts.

    Args:
        record: Record with stable field keys.
        out: Derived values of the record after stage 1.
        flags: Flags of the record after stage 1.
        proposals: Proposed and accepted proposals of the record, oldest first, each with
            `status`, `input_sha256` and `locations`.

    Returns:
        The newest non-stale accepted proposal, else the newest non-stale proposed one
        that only fills empty location columns (auto-acceptance), else None; and every
        non-stale proposed one that would replace a stage-1 location. Both are empty for
        a record that is no measure of its own.
    """
    if out["inferred_record_type"] != "measure" or "refers_to_other_measure" in flags:
        return None, []
    digest = input_sha256(record)
    fresh = [proposal for proposal in proposals if proposal["input_sha256"] == digest]
    # A proposal that only repeats stage 1 changes nothing, so it never shadows another.
    changing = [proposal for proposal in fresh if proposed_columns(out, proposal)]
    accepted = [proposal for proposal in changing if proposal["status"] == "accepted"]
    pending = [proposal for proposal in changing if proposal["status"] == "proposed"]
    conflicts = [proposal for proposal in pending if replaces_stage1_location(out, proposal)]
    fills = [proposal for proposal in pending if proposal not in conflicts]
    return (accepted or fills or [None])[-1], conflicts


def apply_proposal(
    record: dict[str, str], out: dict[str, str], flags: set[str], proposals: list[dict]
) -> set[str]:
    """Fill location columns of a measure from the proposal picked by `pick_proposals`.

    An accepted proposal replaces the stage-1 values of the columns it names. A proposed
    (not reviewed) one applies only if every location it proposes fills an empty stage-1
    column; one that would replace a stage-1 location flags the record as a conflict and
    is not applied, without blocking a gap-filling proposal of the same record.

    Args:
        record: Record with stable field keys.
        out: Derived values; the location columns are filled in place.
        flags: Flags of the record after stage 1.
        proposals: Proposed and accepted proposals of the record, oldest first, each with
            `status`, `input_sha256` and `locations` (`role`, `name`, `kind`).

    Returns:
        The record's flags, with `location_source:llm_proposal` if a proposal applied
        (plus `llm_proposal_reviewed` if a human accepted it), and
        `llm_proposal_conflict` if one conflicts.
    """
    proposal, conflicts = pick_proposals(record, out, flags, proposals)
    if conflicts:
        flags = flags | {CONFLICT_FLAG}
    columns = proposed_columns(out, proposal) if proposal else {}
    if not columns:
        return flags
    accepted = proposal["status"] == "accepted"
    if accepted and replaces_stage1_location(out, proposal):
        if not any(out[column] for column in set(STAGE1_LOCATIONS.values()) - columns.keys()):
            # Every stage-1 location is overruled, so its derivation flags no longer hold.
            flags = {flag for flag in flags if not flag.startswith(STAGE1_LOCATION_FLAGS)}
    for column, locations in columns.items():
        out[column] = LIST_SEPARATOR.join(location["name"] for location in locations)
        if column in KIND_COLUMNS:
            out[KIND_COLUMNS[column]] = locations[0]["kind"]
    flags = flags | {LLM_PROPOSAL_FLAG} | ({REVIEWED_PROPOSAL_FLAG} if accepted else set())
    if out["inferred_location_start"]:
        flags.discard("location_missing")
    if out["inferred_location_end"]:
        flags.discard("location_end_missing")
    elif out["inferred_asset_class"] == "line" and out["inferred_location_start"]:
        flags.add("location_end_missing")
    return flags


def audit_sample(entries: list[tuple[str, str, dict]]) -> list[dict]:
    """Draw the audit sample, stratified by DSO and location kind, with a fixed seed.

    Each DSO gets about 5 % of its entries, at least 3 (or all if it has fewer), split
    over its kinds in proportion by the largest-remainder method. Each stratum is drawn
    with a seed fixed per DSO, so the same entries always give the same sample.

    Args:
        entries: DSO slug, location kind and review row of each auto-accepted proposal.

    Returns:
        The sampled review rows, by DSO and kind.
    """
    strata: dict[str, dict[str, list[dict]]] = {}
    for dso, kind, row in sorted(entries, key=lambda entry: entry[2]["proposal_id"]):
        strata.setdefault(dso, {}).setdefault(kind, []).append(row)
    sample = []
    for dso, kinds in sorted(strata.items()):
        total = sum(len(rows) for rows in kinds.values())
        count = min(total, max(3, math.ceil(total * 0.05)))
        quotas = {kind: count * len(rows) / total for kind, rows in kinds.items()}
        shares = {kind: int(quota) for kind, quota in quotas.items()}
        by_remainder = sorted(quotas, key=lambda kind: (shares[kind] - quotas[kind], kind))
        for kind in by_remainder[: count - sum(shares.values())]:
            shares[kind] += 1
        rng = random.Random(dso)
        for kind, rows in sorted(kinds.items()):
            sample += rng.sample(rows, shares[kind])
    return sample
