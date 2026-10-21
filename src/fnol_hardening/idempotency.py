"""Idempotency store for FNOL intake and claim-record creation.

The same key and the same body return the original result. The same key
with a different body is a conflict and does not write a second record.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from fnol_foundation.canonical import canonical, digest


class IdempotencyConflict(Exception):
    def __init__(self, key: str):
        super().__init__(f"idempotency key {key} was reused with a different body")
        self.key = key
        self.error_code = "idempotency_conflict"


class IdempotencyStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT key, fingerprint, response_json FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "key": row["key"],
            "fingerprint": row["fingerprint"],
            "response": json.loads(row["response_json"]),
        }

    def put(self, key: str, fingerprint: str, response: dict[str, Any]) -> None:
        body = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT fingerprint FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise IdempotencyConflict(key)
                return
            db.execute(
                "INSERT INTO idempotency (key, fingerprint, response_json) VALUES (?, ?, ?)",
                (key, fingerprint, body),
            )

    def execute(
        self,
        key: str,
        fingerprint: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run ``operation`` once for this key. A second identical call replays."""
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ValueError("idempotency key must be 1 to 128 characters")
        with self._lock:
            existing = self._get_unlocked(key)
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise IdempotencyConflict(key)
                replay = dict(existing["response"])
                replay["replayed"] = True
                replay["created"] = False
                return replay
            response = operation()
            if not isinstance(response, dict):
                raise TypeError("idempotent operation must return an object")
            stored = dict(response)
            stored["replayed"] = False
            body = json.dumps(stored, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            with self._connect() as db:
                db.execute(
                    "INSERT INTO idempotency (key, fingerprint, response_json) VALUES (?, ?, ?)",
                    (key, fingerprint, body),
                )
            return stored

    def _get_unlocked(self, key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT key, fingerprint, response_json FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "key": row["key"],
            "fingerprint": row["fingerprint"],
            "response": json.loads(row["response_json"]),
        }


def fingerprint(value: Any) -> str:
    return digest(value)


def intake_key(case_id: str, document_set_sha256: str) -> str:
    """Stable key for one identical FNOL delivery."""
    return "intake:" + digest({"case_id": case_id, "document_set_sha256": document_set_sha256})[:48]


def canonical_fingerprint(value: Any) -> str:
    return digest(json.loads(canonical(value)))
