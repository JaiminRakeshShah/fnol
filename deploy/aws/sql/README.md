# FNOL SQL

Current schema is PostgreSQL, applied by `tools/migrate.py` from
`postgres/*.sql`. The files are versioned. Once a file has been applied to a
namespace it is not edited; add a new file for the next change.

`retired-azure/` is the unused T-SQL from the Azure SQL path. The application
does not execute it. Do not apply it to RDS.

There is no load of old SQLite files. Intake reads evidence from S3 (or the
local document directory) and writes new revisions into Postgres.

Namespaces:

- `FNOL_PG_NAMESPACE=shared` (default) uses schemas `input`, `output`, `trace`, `mock`, and `desk`.
- `isolate` (CI and the Postgres test run) creates a schema set per state directory so cases do not collide.
