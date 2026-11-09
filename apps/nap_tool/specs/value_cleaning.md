<!--
SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut

SPDX-License-Identifier: Apache-2.0
-->

# Spec: value cleaning during harmonization

## Problem

The column mapping merges heterogeneous source columns into one target field, but the values stay heterogeneous: `12.000 T€`, `90 Mio. €` and `583.601` in one cost field; `01/2024`, `1/2022`, `Dez 29` in one date field; `vorgese-↵hene Maß-↵nahme` and `Vorgesehene Maßnahmen` as one status. Such fields cannot be counted, filtered or summed (see `Datenbereinigung_Beispiele_und_Plan.pdf`, part 2).

## Solution

Values are cleaned deterministically **per source column, before merging**, using the knowledge the mapping provides (target field type, source column header, source table). Cleaning is a pure function called from `harmonize_table` on every apply — no separate stored cleaned layer, since rerunning deterministic rules is cheap. AI only proposes the rules (types, units, choice lists); it never touches cells. A human reviews and edits every rule in the mapping editor.

```
table_compared ──► clean(value, field type, source column unit, table number format) ──► table_harmonized_output
                                                                                           data       (cleaned CSV)
                                                                                           cells_json (changed / unresolved cells)
```

## Rules

### Where configuration lives

| Setting | Scope | Stored in |
|---|---|---|
| Type (`money`, `number`, `date`, `choice`, `text`) | target field | mapping JSON (`fields[].type`) |
| Target unit (`number` only; `money` is always €) | target field | mapping JSON (`fields[].unit`) |
| Choice list: canonical value → synonyms | target field | mapping JSON (`fields[].choices`) |
| Source unit (e.g. `T€`, `Mio. €`, `km`) | source column | mapping JSON; pre-filled by parsing the header (`Kosten [Mio. €]`) |
| Number format (thousands / decimal separator) | source table (`table_harmonized_id`) | mapping JSON (`number_formats`); default German (`.` / `,`) |
| Unit families and conversion factors | global | `config/cleaning.yaml` (`units`) |
| Placeholder tokens (`-`, `Bitte auswählen!`, `Noch nicht bekannt`, …) | global | `config/cleaning.yaml` (`null_tokens`) |

- Type is set per target field only, never per source column.
- `config/cleaning.yaml` is loaded with PyYAML and validated with Pydantic, like `config/providers.yaml`; unknown families or duplicate aliases fail loudly.
- Fields without a type (existing mappings) are treated as `text`.
- The mapping `sha256` fingerprint covers the cleaning config, so the same mapping always yields the same output.
- **Carry-over**: re-deriving a mapping (`derive_mapping`) or editing it copies the cleaning config from the active mapping, matched by `field_key` (type, unit, choices), source column name (source unit) and `table_harmonized_id` (number format). New fields get the heuristic suggestion. The editor keeps a field's `key` on rename.

### Collision check

Two columns of the same source table must never map to the same target field. Saving and applying a mapping raise `ValueError` naming the table and columns. `_first_value` is removed; each target field has at most one source column per table. (The current mapping has 0 such collisions across 125 tables.)

### Cleaning order per cell

1. **Normalize** (all types): join hyphenated line breaks when the next character is lowercase (`Geneh-↵migung` → `Genehmigung`), keep the hyphen before uppercase/digits (`110kV-↵Kabel` → `110kV-Kabel`), replace remaining line breaks with a space, collapse whitespace, strip.
2. **Placeholder**: if the normalized value matches a `null_tokens` entry (case-insensitive) → empty, status `converted`. `-` means empty, never 0.
3. **Type rule** (below). Anything the rule cannot parse → status `unresolved`.

### `text`

Normalization and placeholders only. Used for free text, IDs (`lfd. Nr.`: `3a`, `10,1` are never parsed as numbers) and locations (`Teilnetzgebiet` etc.; no region aliasing, no splitting).

### `money` and `number`

- **Separators**, using the source table's number format (German defaults shown):
  1. both `.` and `,` present → the last one is the decimal separator
  2. only the decimal separator → decimal (`1,6` → `1.6`, `13,082` → `13.082`)
  3. only the thousands separator and every group after it has exactly 3 digits → thousands (`3.880` → `3880`)
  4. only the thousands separator otherwise → decimal (`0.5`)
  5. spaces inside digit runs are removed
- **Units**: a unit in the cell overrides the source column unit; without either, the factor is 1. The unit must belong to the field's family and is converted to its canonical unit (`money` → €; `number` → the field's target unit). A unit from another family (`141 Stück` in a km field) → `unresolved`.
- Leading `+` is dropped; `-` as a sign is kept (`-16,6` → `-16.6`).
- `unresolved`: ranges (`50-160`), multiplication (`2x 40 MVA`), qualifiers (`ca.`, `min.`), several values in one cell, any other text.
- No rounding; no plausibility limits.

Initial `config/cleaning.yaml`:

```yaml
units:
  money:  {canonical: "€",     units: {"€": 1, "T€": 1000, "Tsd. €": 1000, "Mio. €": 1000000, "Mio.": 1000000}}
  length: {canonical: "km",    units: {"km": 1, "m": 0.001}}
  power:  {canonical: "MVA",   units: {"MVA": 1, "kVA": 0.001, "MW": 1, "kW": 0.001}}
  count:  {canonical: "Stück", units: {"Stück": 1, "St": 1, "Stk.": 1}}
null_tokens: ["-", "---", "Bitte auswählen!", "keine Angabe", "keine Angabe möglich", "Noch nicht bekannt", "in Bearbeitung", "noch in Klärung"]
```

### `date`

Output is an ISO string whose length encodes precision: `2026`, `2024-01`, `2027-12-31`.

| Input | Output |
|---|---|
| `MM/JJJJ`, `M/JJJJ` | `JJJJ-MM` |
| `JJJJ` | `JJJJ` |
| `TT.MM.JJJJ` | `JJJJ-MM-TT` |
| `Mon JJ`, `Mon JJJJ` (`Dez 29`, `Jan 24`) | `2029-12`, `2024-01` |

Month names (`Jan`, `Jän`, `Feb`, …, `März`, …, `Dez`) are a code constant. `unresolved`: Excel serial numbers (`46752`), ranges (`01/2025-28`, `2024-2028`), year plus status (`2032 (in Genehmigungsvorbereitung)`), Excel errors (`#BEZUG!`, note "Fehler in Quelle").

### `choice`

```json
"type": "choice",
"choices": {"vorgesehene Maßnahme": ["Vorgesehene Maßnahmen"], "konkrete Planung": []}
```

The normalized value is compared case-insensitively against each canonical value and its synonyms. A match → the canonical value; no match → `unresolved`. No fuzzy matching at runtime — similar but different values (`Maßnahme in Planung`) must be decided explicitly. Content answers such as `keine` in "Geprüfte Alternativen" are synonyms, not placeholders.

### Output

- `table_harmonized_output.data`: CSV with cleaned values only; `unresolved` cells are empty. Numbers use `.` as decimal separator, no thousands separator, no unit in the cell.
- New column `table_harmonized_output.cells_json` (sparse): one entry per changed or unresolved cell, `{row, field_key, source, original, status, note}` with `status` ∈ `converted` | `unresolved`. Unchanged cells are not listed. Created on demand like the other harmonization tables.
- Preview and CSV download offer a toggle **unresolved: empty | original**; the "original" variant is filled back from `cells_json` at read time, not stored twice.
- Harmonized view: `converted` cells are subtly tinted, `unresolved` cells red; hover shows the original. German number formatting only in the UI (`Intl.NumberFormat('de-DE')`).

### Editor

Per target field: type dropdown, target unit (`number`), choice list editor showing distinct normalized values with counts. Per source column: unit field (shown for `money`/`number`). Per source table: number format (German / English / custom). No per-cell manual editing.

### Suggestions (heuristic + optional AI)

- A "suggest" button (per field or for all fields) fills the editor **unsaved**; existing edits are never overwritten without confirmation.
- **Heuristic** (always runs): type from header keywords (`€`, `Kosten` → `money`; `[MM/JJJJ]`, `Zeitpunkt`, `Jahr` → `date`; …), source units parsed from headers, choice groups from identical normalized forms (most frequent spelling becomes canonical), number format per table by counting separator patterns.
- **AI** (optional): available when the `ai` extra (`anthropic`) is installed **and** `ANTHROPIC_API_KEY` is set in `.env` (added to `.env.example`); model configurable, default `claude-sonnet-5-5`. The server reports `ai_available`; without it the button reads "Vorschlag (Heuristik)". The model receives headers plus distinct values with counts — never whole tables — and returns structured JSON (type, target unit, choice groups) validated with Pydantic. On error or invalid output the heuristic result is used, the error is logged, and the UI shows a notice.
- No offline suggestion file.

## Implementation order

1. Core: `database_ui/cleaning.py` (pure functions), `config/cleaning.yaml` + loader, integration in `harmonize_table`, `cells_json`, collision check. Tests only.
2. Output: empty/original toggle in preview and download, cell markers in the harmonized view.
3. Editor: type, units, choices, number formats; carry-over on re-derive.
4. Suggestions: heuristic, then optional runtime AI.

## Out of scope

Working through `unresolved` values (review panel, AI cleaning of the remainder), ranges and periods (begin/end), splitting cells with several values or quantities into separate fields, location handling (region aliases, gazetteer, city vs. district), plausibility limits, locale-specific CSV export (`;`/`,`), per-cell manual edits.
