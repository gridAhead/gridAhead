# Data lives in a separate repository, the database holds only metadata

PDFs and tables used to be BLOBs in one 333 MB SQLite file: opaque, not diffable, not traceable outside the tool. All payload now lives as files in the separate git repository `nap_data` (`$NAP_DATA_DIR`, pushed only to the internal GitLab so data never reaches GitHub); `nap_tool.sqlite` beside them stores metadata, relationships, review state and each file's relative path with its SHA-256. Files are checked against their hash when read and never edited in place; a new result is a new file.

## Consequences

- Committing and pushing `nap_data` is manual and separate from `nap_tool`.
- Tests never touch a real `nap_data`; they build their own repository in `tmp_path`.
- Changing the path layout breaks every stored path and requires a DB_VERSION bump (ADR-0003).
