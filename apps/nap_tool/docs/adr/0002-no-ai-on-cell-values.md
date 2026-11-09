# No AI touches cell values

Extraction, cleaning, harmonization and classification are deterministic: the same input and configuration always give the same output. AI may only propose mappings (e.g. a field plan for a scheme) or rules (e.g. classification patterns), and a human reviews them before they take effect. The dataset feeds statements about the grid expansion of real DSOs, so every value must be traceable to a source cell and a rule, not to a model's output.

## Consequences

- Extraction tools never confirm their own output; confirmation happens in extract review, which never modifies the extracted table.
- Classification only appends `inferred_*` columns and never changes source columns.
- AI-based extraction tools (llmPDF, LlamaParse) only locate and transcribe tables; their results go through extract review like any other.
