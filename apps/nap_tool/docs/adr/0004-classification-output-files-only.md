# Classification output is files only

Classification writes `classified/set_<set>/scheme_<scheme>/` (classified table, validation report, unmapped values) and switches it atomically via a symlink; nothing goes into the database. Its rules in `config/classify*.yaml` change often during review, and the output is fully derived from one harmonized table plus that config, so it can always be regenerated. Keeping it out of the schema avoids a DB_VERSION bump (ADR-0003) for every new derived column.
