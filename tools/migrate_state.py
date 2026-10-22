"""One-shot copy of local SQLite state into Azure SQL.

A fresh Azure environment does not need this: intake rebuilds from fixtures and
Blob. Use this only when preserving an existing ``.state`` directory.

Requires FNOL_SQL_SERVER and the azure dependency group. Does not overwrite
existing Azure rows for the same primary keys.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fnol_foundation import azure_sql


TABLES = {
    "input.sqlite": [
        "input_revisions",
        "procedure_sources",
        "tool_payloads",
        "decisions",
    ],
    "output.sqlite": ["drafts"],
    "trace.sqlite": ["trace_events"],
    "mock.sqlite": ["reviews", "records", "keys", "calls", "audit"],
}


def _copy_table(sqlite_path: Path, schema: str, table: str) -> int:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    rows = src.execute(f"SELECT * FROM {table}").fetchall()
    src.close()
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(f"[{c}]" if c.lower() == "key" else c for c in columns)
    inserted = 0
    with azure_sql.connect(schema) as db:
        for row in rows:
            values = tuple(row[c] for c in columns)
            try:
                db.execute(
                    f"INSERT INTO {schema}.{table} ({col_list}) VALUES ({placeholders})",
                    values,
                )
                inserted += 1
            except Exception:
                # Skip duplicates / constraint conflicts.
                continue
    return inserted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=ROOT / ".state",
        help="Local directory with input.sqlite, output.sqlite, trace.sqlite, mock.sqlite",
    )
    args = parser.parse_args(argv)
    if not azure_sql.sql_enabled():
        print("FNOL_SQL_SERVER is not set", file=sys.stderr)
        return 1
    total = 0
    for file_name, tables in TABLES.items():
        path = args.state_dir / file_name
        if not path.is_file():
            print(f"skip missing {path}")
            continue
        schema = azure_sql.schema_for_path(path)
        for table in tables:
            n = _copy_table(path, schema, table)
            print(f"{schema}.{table}: copied {n}")
            total += n
    print(f"done, rows attempted ok={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
