"""Azure SQL backend for the FNOL stores.

Activated when FNOL_SQL_SERVER is set. Requires the optional azure dependency
group (pyodbc, azure-identity). Local tests keep using SQLite.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any

_SCHEMA_FROM_PATH = {
    "input.sqlite": "input",
    "output.sqlite": "output",
    "trace.sqlite": "trace",
    "mock.sqlite": "enterprise",
}


class AzureSQLError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def sql_enabled() -> bool:
    return bool(os.environ.get("FNOL_SQL_SERVER", "").strip())


def schema_for_path(path) -> str:
    name = os.path.basename(str(path)).lower()
    if name in _SCHEMA_FROM_PATH:
        return _SCHEMA_FROM_PATH[name]
    stem = os.path.splitext(name)[0]
    return stem or "input"


def connection_string() -> str:
    server = os.environ.get("FNOL_SQL_SERVER", "").strip()
    database = os.environ.get("FNOL_SQL_DATABASE", "fnol").strip() or "fnol"
    if not server:
        raise AzureSQLError("sql_config", "FNOL_SQL_SERVER is required")
    # Prefer Active Directory managed identity / DefaultAzureCredential token.
    # Username/password is a local fallback only.
    user = os.environ.get("FNOL_SQL_USER", "").strip()
    password = os.environ.get("FNOL_SQL_PASSWORD", "").strip()
    driver = os.environ.get("FNOL_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    if user and password:
        return (
            f"Driver={{{driver}}};Server=tcp:{server},1433;Database={database};"
            f"Uid={user};Pwd={password};Encrypt=yes;TrustServerCertificate=no;"
            "Connection Timeout=30;"
        )
    return (
        f"Driver={{{driver}}};Server=tcp:{server},1433;Database={database};"
        "Authentication=ActiveDirectoryMsi;Encrypt=yes;TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )


class _Row(dict):
    """Dict that also supports sqlite3.Row-style index access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class AzureConnection:
    """Thin adapter so store code can keep using execute / executemany / executescript."""

    def __init__(self, raw, schema: str):
        self._raw = raw
        self.schema = schema
        self.row_factory = None

    def execute(self, sql: str, params=()):
        sql = self._rewrite(sql)
        if sql.strip().upper() in {"BEGIN", "BEGIN IMMEDIATE", "BEGIN TRANSACTION"}:
            if not self._raw.autocommit:
                return _Cursor(None, [])
            self._raw.autocommit = False
            return _Cursor(None, [])
        cur = self._raw.cursor()
        cur.execute(sql, params or ())
        return _Cursor(cur, cur.description)

    def executemany(self, sql: str, seq_of_params):
        sql = self._rewrite(sql)
        cur = self._raw.cursor()
        cur.executemany(sql, list(seq_of_params))
        return _Cursor(cur, cur.description)

    def executescript(self, script: str):
        for statement in _split_sql(script):
            rewritten = self._rewrite(statement)
            if not rewritten.strip():
                continue
            self._raw.cursor().execute(rewritten)
        return self

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False

    def _rewrite(self, sql: str) -> str:
        """Qualify bare table names with the schema for this store file."""
        text = sql.strip()
        if text.upper().startswith("PRAGMA"):
            return "SELECT 1 WHERE 0=1"
        # Map SQLite-only BEGIN IMMEDIATE.
        if text.upper() == "BEGIN IMMEDIATE":
            return "BEGIN TRANSACTION"
        schema = self.schema

        def qualify(match: re.Match[str]) -> str:
            table = match.group(1)
            if table.lower() in {
                "input_revisions",
                "procedure_sources",
                "tool_payloads",
                "decisions",
                "drafts",
                "trace_events",
                "reviews",
                "records",
                "keys",
                "calls",
                "audit",
            }:
                return f"{match.group(0).split(table)[0]}{schema}.{table}"
            return match.group(0)

        patterns = (
            r"\bFROM\s+(\w+)",
            r"\bINTO\s+(\w+)",
            r"\bUPDATE\s+(\w+)",
            r"\bTABLE\s+(\w+)",
            r"\bJOIN\s+(\w+)",
            r"\bDELETE\s+FROM\s+(\w+)",
        )
        out = text
        for pattern in patterns:
            out = re.sub(pattern, qualify, out, flags=re.IGNORECASE)
        # SQLite RAISE(ABORT, ...) becomes RAISERROR for T-SQL trigger bodies
        # already authored in deploy SQL; leave store CREATE TRIGGER scripts alone
        # when running against Azure — init uses deploy scripts instead.
        return out


class _Cursor:
    def __init__(self, cur, description):
        self._cur = cur
        self.description = description

    def fetchone(self):
        if self._cur is None:
            return None
        row = self._cur.fetchone()
        if row is None:
            return None
        if not self.description:
            return row
        keys = [col[0] for col in self.description]
        return _Row(zip(keys, row))

    def fetchall(self):
        if self._cur is None:
            return []
        rows = self._cur.fetchall()
        if not self.description:
            return list(rows)
        keys = [col[0] for col in self.description]
        return [_Row(zip(keys, row)) for row in rows]


def _split_sql(script: str) -> list[str]:
    parts = []
    buf: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return parts


@contextmanager
def connect(schema: str):
    try:
        import pyodbc
    except ImportError as exc:
        raise AzureSQLError(
            "sql_deps",
            "pyodbc is required for Azure SQL mode; install the azure dependency group",
        ) from exc
    raw = pyodbc.connect(connection_string(), autocommit=False)
    # Ensure the schema exists; tables come from deploy/azure/sql/*.sql
    cur = raw.cursor()
    cur.execute(
        """
        IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = ?)
        EXEC(N'CREATE SCHEMA [' + ? + N']')
        """,
        (schema, schema),
    )
    raw.commit()
    db = AzureConnection(raw, schema)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
