<!--
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Classification

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

| Column | Content |
| --- | --- |
| `inferred_record_type` | `measure`, `collective` (Sammler, pauschal, Kleinstmaßnahmen, Maßnahmenregion …) or `overview` |
| `inferred_project_category`, `inferred_project_status`, `inferred_permit_status`, `inferred_primary_driver`, `inferred_existing_bottleneck`, `inferred_forecast_bottleneck` | vocabulary codes of the source columns |
| `inferred_measure_type` | normalized project category; from name/description if the column is empty |
| `inferred_asset_type` | primary asset type, see below |
| `inferred_asset_types` | all asset types, primary first |
| `inferred_asset_class` | `line`, `station` or `other` of the primary type |
| `inferred_grid_level` | grid levels `EHV`, `EHV/HV`, `HV`, `HV/MV`, `MV`, `MV/LV`, `LV` (or `all`): the reported level first, then the levels of the asset codes; from the text only if both are missing |
| `inferred_voltage` | nominal voltage in V per grid level, aligned with `inferred_grid_level`; `upper/lower` for transformation levels; an unknown entry stays empty (`MV,LV` → `,400`) |
| `inferred_line_capacity_change_mva`, `inferred_station_capacity_change_mva` | capacity change by asset class |
| `inferred_location_start`, `_end`, `_via` | locations as written in the source; end and via points only for lines |
| `inferred_location_start_kind`, `_end_kind` | `substation`, `switching_station`, `local_substation` (station keyword before the name), `search_area`, `street_address`, `code` or `place` |
| `inferred_object_ref` | line, plant and station IDs (`Bl. 2473`, `N1`, `UW93`) |
| `inferred_quality_classification` | `high`, `medium` (asset type from description or codes, level from text), `low` (asset type or level missing, level conflict) or `none` |
| `inferred_quality_location` | `high`, `medium` (from description, split by hyphen or underscore route, several stations, line end missing), `none` or `not_applicable` (collective, reference rows) |
| `inferred_flags` | quality and data flags, e.g. `asset_type_from_codes`, `grid_level_conflict`, `voltage_inferred`, `location_source:measure_name`, `implausible:line_length_km`, `unresolved:planned_start`, `unmapped:grid_level`, `duplicate_of=<row_id>` |

### Asset types

`substation`, `switching_station`, `local_substation`, `overhead_line`, `cable`,
`line_or_cable` (line type unknown), `transformer`, `switchgear`,
`reactive_power_compensation`, `earth_fault_compensation`, `voltage_regulator`,
`line_component`, `secondary_tech`, `grid_connection`, `network` (only when nothing more
specific is named), `other`.

Sources in order: free-text `asset_type` cell (NAP 2024), measure name, description,
then the NAP 2026 asset codes (`asset_codes` in the YAML):

| Code | Asset type | Grid level |
| --- | --- | --- |
| 201 | substation | EHV/HV |
| 301 | line_or_cable | HV |
| 302 | line_component | HV |
| 401 | substation | HV/MV |
| 501 | line_or_cable | MV |
| 601 | local_substation | MV/LV |
| 701 | line_or_cable | LV |
| 801 | secondary_tech | |
| 802 | reactive_power_compensation | |

Codes add their asset types when the text names no asset of the same class. Among
code-derived types, the code on the reported grid level comes first. When the text only
names two or more stations as route ends ("ST A > ST B") and a code says line, the line
comes first. Cable designations (NKBA, NA2XS(F)2Y, NAYY …) count as cable.

`inferred_voltage` takes a single explicit voltage from the text even when it lies on
another level than the reported one (flag `voltage_other_level`). `line_or_cable` is
refined to `overhead_line` or `cable` by `line_construction_type` (Freileitung,
Erdkabel).

## Compact sheet check

Many DSOs publish a compact sheet (`Datenblatt vnbdigital.de`) whose km, MVA, station
counts and costs are totals over their measure list. The check compares the classified
records with these totals. It runs with the classification, for the NAP 2026 round only
(`validation.compact_sheet` in `config/classify_2026.yaml`).

**Marking.** `document.is_compact_sheet` marks one XLSX document per DSO and NAP round
(overview documents list, `PATCH /api/overview/documents/{id}/compact-sheet`; marking a
second document replaces the first). If the sheet is embedded in the measure workbook,
mark the workbook. DSOs without a marked sheet get metric `compact_sheet` = `empty`.

**Reading.** The marked workbook is read with `openpyxl` (cached values; the extracted
table is not used). The sheet is the one whose `B1` starts with `Erwarteter
Netzausbaubedarf bis 2045`. The template is located by its labels: the row with
`Projektkategorie`, the horizon headers (`2025 bis 2030 (T+5)` …), the grid-level labels
above them and the quantity headers (`Anzahl`, `MVA`, `Kilometer`, `geschätzter
Bedarf`); a note row between horizon and quantity headers is skipped. A wrong or missing
label gives the DSO `fail` with "unexpected layout" and nothing is parsed. Grid levels
marked `Netzebene wird nicht betrieben`, or absent from the sheet, are not compared. Rows
named `Teilnetzgebiet nicht benannt` are dropped, and the sheet's own totals are ignored:
DSO totals are summed from the subgrid cells. Cells with units ("140 km", "3.0 Mio.
Euro") are read as numbers. An explicit `0` means "no need", an empty cell is missing
(`empty`, never a deviation).

**Comparison.** Records are `measure` and `collective` rows of the round, without rows
flagged `duplicate_of=`. The key is DSO × subgrid area × grid level (first entry of
`inferred_grid_level`) × planning horizon (source column `planning_horizon`: `T+5`,
`T+10`, `Zielnetz 2045`; anything else is counted as unassigned, never guessed from
dates) × category group × quantity, and the same key as a DSO total.

| Category group | `inferred_project_category` |
| --- | --- |
| Neubau | `new` |
| Ersatz(neubau) mit Erhöhung; Netzoptimierung und -verstärkung | `replacement_increase`, `optimization` |
| Reiner Ersatz (1:1) / Rückbau / Altlastentsorgung | `replacement_no_increase`, `dismantling` |

- Lines (HV, MV, LV): km (`line_length_km`) and cost. Stations (EHV/HV, HV/MV, MV/LV):
  MVA (`capacity_change_mva`), cost and station count.
- Cost is `reported_amount_eur`; the sheet's `geschätzter Bedarf` is in Mio. EUR
  (`cost_divisor`).
- Station count is the number of `measure` records with `inferred_asset_class ==
  station` (collective rows excluded). DSOs fill the count in by hand, so its status is at
  worst `warn`.
- Subgrid areas are matched after strip and casefold. Records without `subgrid_area` count
  toward the DSO total only, unless the sheet names exactly one subgrid area. Names that
  match nothing on either side are listed as `unmatched_subgrid_areas`; their records
  still count toward the total.
- A cell the sheet fills but to which no record contributes a value (the measure list has
  no cost column, lists no measures for that horizon, …) is a coverage gap: the measure
  list says nothing, so it is not a deviation. It counts as `empty` and is counted per DSO
  in `uncovered_cells`. Only cells with contributing records can warn or fail. A DSO with
  nothing comparable gets `empty`. The station count is always compared.
- Tolerance on the relative deviation: pass ≤ 1 %, warn ≤ 10 %, else fail. An explicit 0
  against a nonzero sum fails.

**Report.** `validation_report.json` / `.md` carry one metric `compact_sheet` per DSO
(worst cell status; value = number of non-pass cells), and the sections
`compact_sheet_deviations` (non-pass cells only), `unmatched_subgrid_areas`,
`unassigned_planning_horizons` and `compact_sheet_documents`. The classify page shows
them in the tab **Kompaktblatt-Abgleich** (EN "Compact sheet check").
