"""Least-privilege guard for the FNOL copilot.

Every component has an allowlist. Actions past the human boundary
(coverage, liability, fraud, reserve, settlement, denial, payment, and
approving a review) raise PrivilegeError for the copilot. The human
operator may approve or reject a review. Nobody in this system may pay,
deny, or adjudicate a claim.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# The copilot and the operator CLI both refuse these. They are the human
# boundary from BRIEF.md and AUTO-TRIAGE-01: no final claim decision.
FORBIDDEN_FOR_EVERYONE = frozenset({
    "approve_claim",
    "deny_claim",
    "pay_claim",
    "set_reserve",
    "settle_claim",
    "adjudicate_coverage",
    "adjudicate_liability",
    "adjudicate_fraud",
    "update_claim",
})

# approve_review / reject_review are the operator CLI only. The analyst
# must not call them. See README "Human approval and recovery".
ALLOWLIST = {
    "intake": frozenset({"read_health", "read_case_list", "read_document"}),
    "policy": frozenset({"read_policy"}),
    "rules": frozenset({"read_claims"}),
    "citations": frozenset({"read_stored_evidence", "read_procedure"}),
    "analyst": frozenset({
        "read_health",
        "read_case_list",
        "read_policy",
        "read_claims",
        "read_record",
        "read_stored_evidence",
        "build_draft",
        "submit_review",
        "poll_review",
        "file_record",
    }),
    "shadow": frozenset({"read_packet", "write_summary_slot"}),
    "human_operator": frozenset({
        "approve_review",
        "reject_review",
        "read_pending",
        "read_audit",
        "reset_mock_state",
    }),
}

_HTTP_RULES = (
    ("GET", re.compile(r"^/health$"), "read_health"),
    ("GET", re.compile(r"^/v1/cases$"), "read_case_list"),
    ("GET", re.compile(r"^/v1/cases/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/policy$"), "read_policy"),
    ("GET", re.compile(r"^/v1/cases/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/claims$"), "read_claims"),
    ("POST", re.compile(r"^/v1/reviews$"), "submit_review"),
    ("GET", re.compile(r"^/v1/reviews/[A-Za-z0-9._-]{1,128}$"), "poll_review"),
    ("GET", re.compile(r"^/v1/records/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"), "read_record"),
    ("POST", re.compile(r"^/v1/records$"), "file_record"),
)


class PrivilegeError(PermissionError):
    def __init__(self, actor: str, action: str):
        super().__init__(f"{actor} cannot {action}")
        self.actor = actor
        self.action = action
        self.error_code = "privilege_denied"


def authorize(actor: str, action: str) -> None:
    """Raise PrivilegeError when ``actor`` may not perform ``action``."""
    if not isinstance(actor, str) or not isinstance(action, str):
        raise PrivilegeError(str(actor), str(action))
    if action in FORBIDDEN_FOR_EVERYONE:
        raise PrivilegeError(actor, action)
    allowed = ALLOWLIST.get(actor)
    if allowed is None or action not in allowed:
        raise PrivilegeError(actor, action)


def action_for_http(method: str, url: str) -> str:
    """Map a mock URL to an action name, or ``unsupported_operation``."""
    path = urlsplit(url).path or url
    if not path.startswith("/"):
        path = urlsplit("http://local" + (path if path.startswith("/") else "/" + path)).path
    verb = method.upper()
    for rule_method, pattern, action in _HTTP_RULES:
        if verb == rule_method and pattern.fullmatch(path):
            return action
    lowered = path.lower()
    if "pay" in lowered or "payment" in lowered:
        return "pay_claim"
    if lowered.rstrip("/").endswith("/approve") or "/approve" in lowered:
        return "approve_review"
    if lowered.rstrip("/").endswith("/reject") or "/reject" in lowered or "deny" in lowered:
        return "deny_claim"
    if "reserve" in lowered:
        return "set_reserve"
    if "settl" in lowered:
        return "settle_claim"
    return "unsupported_operation"


def authorize_http(actor: str, method: str, url: str) -> str:
    """Raise before any socket is opened when the request is not allowed.

    Returns the action name when it is allowed.
    """
    action = action_for_http(method, url)
    authorize(actor, action)
    return action
