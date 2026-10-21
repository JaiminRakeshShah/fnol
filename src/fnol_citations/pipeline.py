"""One-call citations pipeline. MCP and local callers share this entry."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fnol_foundation.stores import Stores, state_dir

from fnol_citations.service import CitationError, run_citations

ROOT = Path(__file__).resolve().parents[2]


def start_citations(
    case_id: str | None = None,
    *,
    state_dir_path: str | Path | None = None,
    policies_dir: str | Path | None = None,
) -> dict:
    """Slice citations for one case, or for every case with an input revision.

    Reads input.sqlite and the policy wording files. Does not call the mock:
    policy and claims snapshots are the ones Steps 2 and 3 already stored.
    """
    directory = Path(state_dir_path) if state_dir_path is not None else state_dir()
    policies = Path(policies_dir or os.environ.get("FNOL_POLICIES_DIR", ROOT / "data" / "dev" / "policies"))
    stores = Stores(directory)
    trace_id = uuid.uuid4().hex
    try:
        if case_id:
            case_ids = [case_id]
        else:
            case_ids = [row["case_id"] for row in stores.input.latest_loss_keys()]
            if not case_ids:
                raise CitationError("no_cases", "input.sqlite has no revisions; run intake first")
        cases = [
            run_citations(cid, stores, policies_dir=policies, trace_id=trace_id)
            for cid in case_ids
        ]
        return {
            "input_sqlite": str(stores.input.path.resolve()),
            "trace_sqlite": str(stores.trace.path.resolve()),
            "trace_id": trace_id,
            "case_count": len(cases),
            "cases": cases,
        }
    finally:
        stores.close()
