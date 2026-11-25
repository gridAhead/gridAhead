---
name: nap-locate-measures
description: Location proposals for nap-tool records that stage 1 could not locate, via gazetteer lookup and `nap-tool propose add`. Use when asked to locate measures of a set and scheme.
version: "0.1"
---

# Locate measures

You read each record's source text, look its names up in the gazetteer, and send location **proposals** to `nap-tool propose add`. Code checks every proposal and a human reviews them (ADR-0002, ADR-0008 in `apps/nap_tool/docs/adr/`); your job is faithful reading, nothing more. Vocabulary: `apps/nap_tool/GLOSSARY.md`.

## Setup

1. Get from the user the set id, the scheme id, optionally a DSO MaStR number, and how many chunks to do (default: until done).
2. Run every command from the repo root with `NAP_DATA_DIR` exported in the shell; `gazetteer` reads only the environment, never a `.env` file.
   - `uv run --project apps/nap_tool nap-tool propose …`
   - `uv run --project modules/gazetteer gazetteer match …`
3. Take the two stamps for `propose add`: `--model` is your exact model ID from your system prompt; `--skill-version` is the `version` in this file's frontmatter.

Done when you hold set id, scheme id, chunk count, model and version, and `echo $NAP_DATA_DIR` prints a path.

## Loop

Keep a **skip list**: row ids you will not propose for, each with its reason. `propose rows` prints every record without a stored proposal again on each call, so the skip list is how you move past them.

Repeat per chunk:

1. **Fetch**: `nap-tool propose rows --set-id S --scheme-id C [--dso D] --limit N`, with N = 20 plus the length of the skip list. Drop skip-list rows from the output.
2. **Read** each package: `measure_name`, `measure_description` and `upstream_grid_node` are the source text; `location_start`, `location_end` and `location_via` are what stage 1 already found; `asset_class` and `grid_level` are stage 1's reading. Collect the location names the text names.
3. **Match**: one `gazetteer match --dso <dso_mastr_nr> --level <level> NAME [NAME …]` per record, all its names in one call (records with the same DSO and level may share a call). `<level>` is the first entry of the record's comma-separated `grid_level`. Omit `--level` when `grid_level` is empty or `all`, or when the gazetteer answers that the DSO has no area for that level. If it answers "unknown DSO MaStR number", propose from the text alone, without `candidate`.
4. **Propose**: write one proposal line per record that has a location to propose (see Rules); every other record goes on the skip list. Pipe the chunk's proposal lines in with a quoted heredoc (`<<'EOF'`) to `nap-tool propose add --set-id S --scheme-id C --model M --skill-version V`.
5. **Fix**: `propose add` prints one report per input line, matched by its `line` number (`row_id` is null for a malformed line): `"status": "stored"`, or `"status": "rejected"` with a `reason`. Correct each rejected proposal line and resend it once; still rejected → skip list.

A chunk is done when every package in it is `stored` or on the skip list. The run is done when a fetch returns only skip-list rows or the chunk count is reached; then write the Summary.

### Proposal line

```json
{"row_id": "1234-56", "locations": [{"role": "start", "name": "Albbruck", "kind": "substation",
  "evidence": {"field": "upstream_grid_node", "quote": "UW Albbruck"}, "candidate": "node/123456"}]}
```

- `role`: per `asset_class`. For `line`: `start`, `end`, `via`. Otherwise: `site` for a station or plant location, `area` for a search area or region. `site` and `area` fill the start location.
- `kind`: `substation`, `switching_station`, `local_substation`, `search_area`, `street_address`, `code` or `place`. A station keyword in the quote decides the station kinds by the stage-1 keyword lists, `locations.types` in `apps/nap_tool/config/classify.yaml` (UW → `substation`, SA → `switching_station`, ONS → `local_substation`, Suchraum → `search_area`). A name without a keyword is a `substation` when it comes from `upstream_grid_node` or its candidate is a station, otherwise a `place`.
- `name`: the location without its station keyword ("UW Albbruck" → "Albbruck").
- `evidence`: the source `field` and the `quote` from it, per *Verbatim quote*.
- `candidate`: per *Candidate spelling*.

If `propose add` rejects a line's shape, see "Location proposals" in `apps/docs/content/docs/nap-tool/index.mdx`.

## Rules

- **Fill gaps only.** Propose a role only when its stage-1 column is empty: `start`/`site`/`area` → `location_start`, `end` → `location_end`, `via` → `location_via`. `classify` drops the whole proposal when any of its locations hits a filled column, so for a power line with a start but no end, propose the end alone. No empty column to fill → skip list. A filled column that looks wrong goes into your Summary.
- **Candidate spelling.** When a candidate is the same place or station the text names, differing only in spelling (case, ß/ss, umlauts, hyphens, spacing, station prefix), use the candidate's `name` and set `candidate` to its `osm`. Otherwise write the name as the source spells it and leave `candidate` out.
- **Verbatim quote.** Every location quotes the source span that names it, copied character for character from the field it names; `propose add` rejects a quote it cannot find there.
- **Qualifiers stay.** Ost, West, Nord, Süd, A/B, "2" and similar are part of the name: "UW Musterstadt Ost" → "Musterstadt Ost". A candidate missing the qualifier is a different station; write the source spelling.
- **Abbreviations stay as written.** Expand one only when a candidate spells out the same place or station.
- **Numbers are grid objects.** Line, feeder, mast and plant numbers ("Mast 74", "MS 4", "Anlage 218", "Bl. 4512") identify grid objects, not locations; they never become a proposal.
- **No location, no proposal.** When the text names no place, station, street or search area, the record goes on the skip list.
- **Locations only.** Grid level, voltage and asset type belong to stage 1; one that looks wrong goes into your Summary.

## Summary

When the run ends, report to the user: chunks done; proposal lines stored and rejected; the skip list with reasons; every rejection reason you could not fix; row ids where stage 1 looks wrong; patterns you noticed in the source text.
