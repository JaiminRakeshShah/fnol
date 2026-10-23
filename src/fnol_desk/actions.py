"""Send / accept / reject against the existing hash-bound mock review path."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fnol_desk.auth import AuthError, User
from fnol_foundation.canonical import digest
from fnol_foundation.stores import Stores
from tools.runtime import audit, connect as mock_connect, mock_state_present

ROOT = Path(__file__).resolve().parents[2]


class DeskActionError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def default_mock_url() -> str:
    return "http://127.0.0.1:8767"


def default_mock_state() -> Path:
    return ROOT / ".state" / "mock.sqlite"


def send_to_handlers(
    user: User,
    case_id: str,
    *,
    stores: Stores | None = None,
    mock_url: str | None = None,
    mock_state: Path | None = None,
) -> dict[str, Any]:
    """Analyst submits the unchanged draft into pending review. Does not approve."""
    if user.team != "analysts":
        raise AuthError("forbidden", "only analysts can send drafts to handlers")
    stores = stores or Stores()
    mock_url = (mock_url or default_mock_url()).rstrip("/")
    mock_state = Path(mock_state) if mock_state is not None else default_mock_state()
    record = stores.output.latest_draft(case_id)
    if record is None:
        raise DeskActionError("not_found", f"no draft for {case_id}", 404)

    # If a matching pending review already exists, do not create another.
    if mock_state_present(mock_state):
        with mock_connect(mock_state) as db:
            existing = db.execute(
                """SELECT id, status, hash FROM reviews
                   WHERE case_id = ? AND hash = ? AND status = 'pending'
                   ORDER BY rowid DESC LIMIT 1""",
                (case_id, record.draft_hash),
            ).fetchone()
            if existing:
                stores.output.update_status(
                    record.draft_id, "in_review", review_id=existing["id"]
                )
                return {
                    "case_id": case_id,
                    "review_id": existing["id"],
                    "status": "pending",
                    "draft_hash": record.draft_hash,
                    "already_pending": True,
                }

    body = json.dumps({"case_id": case_id, "draft": record.draft}).encode("utf-8")
    req = urllib.request.Request(
        f"{mock_url}/v1/reviews",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            status = resp.status
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": "mock_http_error"}
        raise DeskActionError(
            str(payload.get("error") or "send_failed"),
            f"mock returned HTTP {exc.code}",
            502,
        ) from exc
    except urllib.error.URLError as exc:
        raise DeskActionError(
            "mock_unreachable",
            "mock enterprise API is not reachable; start tools/runtime.py serve",
            503,
        ) from exc

    if status not in (200, 201):
        raise DeskActionError("send_failed", f"mock returned HTTP {status}", 502)
    review_id = payload.get("review_id")
    returned_hash = payload.get("draft_hash")
    if not isinstance(review_id, str) or returned_hash != record.draft_hash:
        raise DeskActionError("hash_mismatch", "mock draft hash did not match stored draft", 502)
    stores.output.update_status(record.draft_id, "in_review", review_id=review_id)
    return {
        "case_id": case_id,
        "review_id": review_id,
        "status": "pending",
        "draft_hash": record.draft_hash,
        "already_pending": False,
    }


def accept_review(
    user: User,
    case_id: str,
    *,
    stores: Stores | None = None,
    mock_state: Path | None = None,
) -> dict[str, Any]:
    """Handler accepts the pending review whose hash matches the stored draft."""
    if user.team != "handlers":
        raise AuthError("forbidden", "only handlers can accept")
    return _decide(user, case_id, approved=True, reason=None, stores=stores, mock_state=mock_state)


def reject_review(
    user: User,
    case_id: str,
    reason: str,
    *,
    stores: Stores | None = None,
    mock_state: Path | None = None,
) -> dict[str, Any]:
    """Handler rejects; reason is written into the audit detail only."""
    if user.team != "handlers":
        raise AuthError("forbidden", "only handlers can reject")
    if not isinstance(reason, str) or not reason.strip():
        raise DeskActionError("reason_required", "a reject reason is required")
    return _decide(
        user,
        case_id,
        approved=False,
        reason=reason.strip(),
        stores=stores,
        mock_state=mock_state,
    )


def _decide(
    user: User,
    case_id: str,
    *,
    approved: bool,
    reason: str | None,
    stores: Stores | None,
    mock_state: Path | None,
) -> dict[str, Any]:
    stores = stores or Stores()
    mock_state = Path(mock_state) if mock_state is not None else default_mock_state()
    if not mock_state_present(mock_state):
        raise DeskActionError("mock_missing", "mock state database is missing", 503)
    record = stores.output.latest_draft(case_id)
    if record is None:
        raise DeskActionError("not_found", f"no draft for {case_id}", 404)

    with mock_connect(mock_state) as db:
        row = db.execute(
            """SELECT * FROM reviews
               WHERE case_id = ? AND hash = ? AND status = 'pending'
               ORDER BY rowid DESC LIMIT 1""",
            (case_id, record.draft_hash),
        ).fetchone()
        if row is None:
            raise DeskActionError(
                "review_not_pending",
                "no pending review matches this exact draft hash",
                409,
            )
        if row["hash"] != record.draft_hash:
            raise DeskActionError("hash_mismatch", "draft hash does not match review", 409)
        # Defense: recompute digest of stored draft text in the review row
        stored_draft = json.loads(row["draft"])
        if digest(stored_draft) != record.draft_hash:
            raise DeskActionError("hash_mismatch", "review draft body does not match hash", 409)

        status = "approved" if approved else "rejected"
        reviewer = user.display_name
        db.execute(
            "UPDATE reviews SET status=?, reviewer=? WHERE id=?",
            (status, reviewer, row["id"]),
        )
        detail: dict[str, Any] = {
            "review_id": row["id"],
            "reviewer": reviewer,
            "draft_hash": row["hash"],
            "username": user.username,
        }
        if reason is not None:
            detail["reason"] = reason
        audit(db, "human_" + status, case_id, **detail)

    outcome = "approved" if approved else "rejected"
    stores.output.update_status(
        record.draft_id,
        outcome,
        review_id=row["id"],
        outcome=outcome,
    )
    return {
        "case_id": case_id,
        "review_id": row["id"],
        "status": status,
        "reviewer": reviewer,
        "draft_hash": record.draft_hash,
        "reason": reason,
    }
