---
title: Classification
description: How nap-tool classifies a harmonized grid-measure table, which rows it drops, and which columns it derives.
mode: wide
sidebar:
  label: Classification
  order: 1
---

<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

`uv run nap-tool classify --scheme-id <id> [--set-id <id>]` (or **Run classification** in
the UI) reads the harmonized table of a grid-measure set and writes a new generation
`$NAP_DATA_DIR/classified/set_<set>/.versions/scheme_<scheme>_<uuid>/`. The generation
named in `classified/set_<set>/scheme_<scheme>.current` is the current output
(ADR-0006). Each generation holds:

- `classified.csv`: every source column unchanged, plus the derived columns below.
- `validation_report.md` / `.json`: metrics, flag counts, quality grades, dropped rows.
- `unmapped_values.csv`: vocabulary values without a mapping (`dso_slugs` comma-separated).

The rules are deterministic and live in `config/classify.yaml`;
`config/classify_<year>.yaml` is picked automatically for a single-year set. Patterns
applied to case-folded text must use `ss` instead of `ß` (the config check rejects `ß`).

## Dropped rows

Footer, licence and blank rows are not measures. A row is dropped (and listed under
`dropped_rows` in the report) if none of `record_type.identity_fields` is filled, or if
fewer than `record_type.min_filled_fields` content fields (all fields except
`record_type.metadata_fields`) are filled. Overview rows are always kept.

## Derived columns

Identifiers keep their names: `row_id`, `nap_round`, `document_date`, `dso_name`,
`dso_mastr_nr`, `dso_bdew_code`. Everything classified or inferred has the prefix
`inferred_`. List values are comma-separated.

| Column                                                                                                                                                                      | Content                                                                                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `inferred_record_type`                                                                                                                                                      | `measure`, `collective` (Sammler, pauschal, Kleinstmaßnahmen, Maßnahmenregion …) or `overview`                                                                                                                                            |
| `inferred_project_category`, `inferred_project_status`, `inferred_permit_status`, `inferred_primary_driver`, `inferred_existing_bottleneck`, `inferred_forecast_bottleneck` | vocabulary codes of the source columns                                                                                                                                                                                                    |
| `inferred_measure_type`                                                                                                                                                     | normalized project category; from name/description if the column is empty                                                                                                                                                                 |
| `inferred_asset_type`                                                                                                                                                       | primary asset type, see below                                                                                                                                                                                                             |
| `inferred_asset_types`                                                                                                                                                      | all asset types, primary first                                                                                                                                                                                                            |
| `inferred_asset_class`                                                                                                                                                      | `line`, `station` or `other` of the primary type                                                                                                                                                                                          |
| `inferred_grid_level`                                                                                                                                                       | grid levels `EHV`, `EHV/HV`, `HV`, `HV/MV`, `MV`, `MV/LV`, `LV` (or `all`): the reported level first, then the levels of the asset codes; from the text only if both are missing                                                          |
| `inferred_voltage`                                                                                                                                                          | nominal voltage in V per grid level, aligned with `inferred_grid_level`; `upper/lower` for transformation levels; an unknown entry stays empty (`MV,LV` → `,400`)                                                                         |
| `inferred_line_capacity_change_mva`, `inferred_station_capacity_change_mva`                                                                                                 | capacity change by asset class                                                                                                                                                                                                            |
| `inferred_location_start`, `_end`, `_via`                                                                                                                                   | locations as written in the source; end and via points only for lines                                                                                                                                                                     |
| `inferred_location_start_kind`, `_end_kind`                                                                                                                                 | `substation`, `switching_station`, `local_substation` (station keyword before the name), `search_area`, `street_address`, `code` or `place`                                                                                               |
| `inferred_object_ref`                                                                                                                                                       | line, plant and station IDs (`Bl. 2473`, `N1`, `UW93`)                                                                                                                                                                                    |
| `inferred_quality_classification`                                                                                                                                           | `high`, `medium` (asset type from description or codes, level from text), `low` (asset type or level missing, level conflict) or `none`                                                                                                   |
| `inferred_quality_location`                                                                                                                                                 | `high`, `medium` (from description, split by hyphen or underscore route, several stations, line end missing, location proposal), `none` or `not_applicable` (collective, reference rows)                                                  |
| `inferred_flags`                                                                                                                                                            | quality and data flags, e.g. `asset_type_from_codes`, `grid_level_conflict`, `voltage_inferred`, `location_source:measure_name`, `location_source:llm_proposal`, `location_source:reviewed_proposal`, `llm_proposal_conflict`, `implausible:line_length_km`, `unresolved:planned_start`, `unmapped:grid_level`, `duplicate_of=<row_id>` |

### Asset types

`substation`, `switching_station`, `local_substation`, `overhead_line`, `cable`,
`line_or_cable` (line type unknown), `transformer`, `switchgear`,
`reactive_power_compensation`, `earth_fault_compensation`, `voltage_regulator`,
`line_component`, `secondary_tech`, `grid_connection`, `network` (only when nothing more
specific is named), `other`.

Sources in order: free-text `asset_type` cell (NAP 2024), measure name, description,
then the NAP 2026 asset codes (`asset_codes` in the YAML):

| Code | Asset type                  | Grid level |
| ---- | --------------------------- | ---------- |
| 201  | substation                  | EHV/HV     |
| 301  | line_or_cable               | HV         |
| 302  | line_component              | HV         |
| 401  | substation                  | HV/MV      |
| 501  | line_or_cable               | MV         |
| 601  | local_substation            | MV/LV      |
| 701  | line_or_cable               | LV         |
| 801  | secondary_tech              |            |
| 802  | reactive_power_compensation |            |

Codes add their asset types when the text names no asset of the same class. Among
code-derived types, the code on the reported grid level comes first. When the text only
names two or more stations as route ends ("ST A > ST B") and a code says line, the line
comes first. Cable designations (NKBA, NA2XS(F)2Y, NAYY …) count as cable.

`inferred_voltage` takes a single explicit voltage from the text even when it lies on
another level than the reported one (flag `voltage_other_level`). `line_or_cable` is
refined to `overhead_line` or `cable` by `line_construction_type` (Freileitung,
Erdkabel).
