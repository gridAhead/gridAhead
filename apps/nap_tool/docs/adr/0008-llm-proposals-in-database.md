<!--
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Location proposals live in the database, classification output stays files

Claude, guided by the `nap-locate-measures` skill, proposes location names for records that stage 1 could not locate well. Under ADR-0002 such proposals only take effect through deterministic code: `nap-tool propose add` checks each one, a human reviews conflicts and an audit sample, and `classify` applies accepted or auto-accepted proposals. Proposals carry review state, like extract and clean reviews, and are an input to classification that cannot be regenerated without Claude. They are therefore stored in `nap_tool.sqlite` (tables `proposal`, `proposal_location`), keyed by `row_id` and `input_sha256` and independent of any set. This does not contradict ADR-0004: classification *output* is still files only, fully derived from the harmonized table, the config and the proposals.

## Consequences

- Introducing the tables bumped `DB_VERSION`, with an upgrade step (ADR-0003).
- Proposal history is never deleted. A human correction is a new proposal with `model = human`, not an edit.
- A changed source cell changes `input_sha256`, which makes older proposals stale for that row.
