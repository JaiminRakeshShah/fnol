"""One-call rules pipeline. MCP and local callers share this entry."""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from fnol_foundation.stores import Stores, state_dir
from fnol_rules.adapter import fields_from_payload
from fnol_rules.claims import ClaimsFetchResult
from fnol_rules.service import run_rules
from fnol_rules.types import PolicyResult

ROOT = Path(__file__).resolve().parents[2]


class RulesError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


_UNSET = object()

# Step 2 reasons that mean "policy could not be established" for AUTO-TRIAGE-01.
_POLICY_UNAVAILABLE = {"unavailable", "not_found", "wording_missing"}


def policy_result_for(stores: Stores, case_id: str) -> PolicyResult:
    """Per-case Step 2 decision rebuilt from the stored policy snapshot.

    No snapshot means the policy server has not run (or stored nothing because the
    service was unavailable): routing treats that as policy_available=False.
    """
    from fnol_policy.service import decision_from_store

    decision = decision_from_store(stores, case_id)
    if decision is None:
        return PolicyResult(selected_policy_version=None, policy_available=False)
    return PolicyResult(
        selected_policy_version=decision["selected_policy_version"],
        policy_available=decision["reason"] not in _POLICY_UNAVAILABLE,
    )


def start_routing(
    case_id: str | None = None,
    *,
    mock_url: str | None = None,
    state_dir_path: str | Path | None = None,
    selected_policy_version: str | None | object = _UNSET,
    policy_available: bool = True,
    policy_results: dict[str, PolicyResult] | None = None,
    fetch: Callable[..., ClaimsFetchResult] | None = None,
) -> dict[str, Any]:
    """Load latest intake revision(s), fetch claims, route with AUTO-TRIAGE-01.

    Policy comes from Step 2 — Rules never selects intervals. Per case, in order:
    an entry in policy_results, else the stored policy snapshot in input.sqlite,
    else the scalar selected_policy_version/policy_available override (tests only).
    Omit case_id to route every case that has a latest input revision.
    """
    mock_url = mock_url or os.environ.get("FNOL_MOCK_URL", "http://127.0.0.1:8767")
    directory = Path(state_dir_path) if state_dir_path is not None else state_dir()
    stores = Stores(directory)
    try:
        case_ids = _case_ids(stores, case_id)
        routed = []
        for cid in case_ids:
            revision = stores.input.get_revision(cid)
            if revision is None:
                raise RulesError("revision_missing", f"no input revision for {cid}")
            if policy_results and cid in policy_results:
                policy = policy_results[cid]
            elif selected_policy_version is not _UNSET:
                policy = PolicyResult(
                    selected_policy_version=selected_policy_version,  # type: ignore[arg-type]
                    policy_available=policy_available,
                )
            else:
                policy = policy_result_for(stores, cid)
            fields = fields_from_payload(revision.payload)
            result = run_rules(
                cid,
                fields,
                policy,
                base_url=mock_url,
                stores=stores,
                fetch=fetch,
            )
            routed.append({
                "case_id": cid,
                "input_revision": revision.revision,
                **asdict(result),
            })
        return {
            "input_sqlite": str(stores.input.path.resolve()),
            "trace_sqlite": str(stores.trace.path.resolve()),
            "case_count": len(routed),
            "routes": routed,
        }
    finally:
        stores.close()


def _case_ids(stores: Stores, case_id: str | None) -> list[str]:
    if case_id:
        return [case_id]
    keys = stores.input.latest_loss_keys()
    ids = [row["case_id"] for row in keys if row.get("case_id")]
    if not ids:
        raise RulesError("no_cases", "input.sqlite has no revisions; run intake first")
    return ids
