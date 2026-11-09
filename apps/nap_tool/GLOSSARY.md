# nap-tool

Collects the Netzausbaupläne of German distribution system operators, turns their measure
tables into one reviewed, harmonized and classified dataset. Canonical terms are English;
German terms that appear in the source data are given as _source term_.

## Sources

**NAP** (Netzausbauplan):
A grid expansion plan a DSO publishes under § 14d EnWG, listing its planned grid measures.
_Avoid_: Ausbauplan, expansion report

**NAP round**:
One publication cycle of NAPs, identified by its year (e.g. the NAP 2026 round).
_Avoid_: NAP year, edition

**DSO**:
A distribution system operator that publishes a NAP.
_Source term_: VNB (Verteilnetzbetreiber)
_Avoid_: provider, operator, Netzbetreiber

**VNBdigital**:
The public portal where DSOs upload their NAP documents; the only source `discover` reads.

**Document**:
One source file a DSO published for a NAP round, in one of several document kinds.
_Avoid_: file, upload, PDF (as a general term)

**NAP report**:
The PDF document of a NAP: prose plus tables.

**Measure list**:
The spreadsheet document of a NAP with one row per measure.
_Source term_: Maßnahmenplan, Maßnahmenliste

**Compact sheet**:
The spreadsheet document summarizing a NAP as a cross table of grid level, period and category.
_Source term_: Datenblatt vnbdigital.de, Kompaktdarstellung

**Markdown conversion**:
A Markdown rendering of a NAP report, used as a source of its tables.

## Tables and review

**Extracted table**:
One table taken unchanged from a document by one extraction tool.

**Extraction tool**:
The method that produced an extracted table (docling, llmPDF, xlsx, markdown).
_Avoid_: extractor, parser

**Extract review**:
The human check of an extracted table, yielding an optional corrected copy.

**Table type**:
The kind of content an extracted table holds, e.g. Maßnahmentabelle or Regionale Szenarioparameter.

**Table type assignment**:
Giving an extracted table its table type.
_Avoid_: classification, table classification

**Cleaning**:
Turning a reviewed table into typed, unit-normalized columns with a header row and deleted rows.

**Clean review**:
The human check of a cleaned table, yielding an optional corrected copy.

**Confirmed**:
The state of an extract or clean review a human has accepted as correct.
_Avoid_: approved, accepted

**Selected**:
The version that counts for sets: one document per DSO and NAP round, one cleaning per table.
_Avoid_: active, current

**Archived**:
An extracted table hidden from review and sets but kept.
_Avoid_: deleted, ignored

## Harmonization

**Set**:
The scope of a harmonized table: one table type, a selection of DSOs and of NAP rounds.
_Avoid_: harmonization set (in prose), selection

**Scheme**:
A reusable list of target fields and the source columns mapped to each.
_Avoid_: schema, column mapping

**Target field**:
One column of the harmonized table, defined in a scheme.
_Avoid_: harmonized column, field (alone)

**Field source**:
A column of one extracted table that feeds a target field.

**Harmonized table**:
The table produced from a set and a scheme: all records in the scheme's columns.
_Avoid_: harmonized output, merged table

## Classification

**Classification**:
Deriving standardized attributes (record type, asset type, grid level, location, quality)
for each record of a harmonized table.
_Avoid_: categorization; never use for table type assignment

**Record**:
Any kept row of a measure table: a measure, a collective measure or an overview record.
_Avoid_: measure (for the umbrella), row (in prose)

**Measure**:
A record describing one single grid project.
_Source term_: Maßnahme
_Avoid_: project

**Collective measure**:
A record bundling many small projects into one lump-sum entry.
_Source term_: Sammler, pauschal, Kleinstmaßnahmen

**Overview record**:
A record summarizing or referencing other records, e.g. a total per grid level.

**Asset code**:
A three-digit code of the NAP 2026 measure lists naming the affected equipment and grid level.
_Source term_: Betriebsmittel-Zuordnungscode

**Grid level**:
A voltage level or transformation level of the grid: EHV, EHV/HV, HV, HV/MV, MV, MV/LV, LV.
_Source term_: Netzebene, Spannungsebene
