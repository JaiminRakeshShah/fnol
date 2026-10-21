"""One-call policy pipeline. MCP and local callers share this entry."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable

from fnol_foundation.stores import Stores, state_dir
from fnol_policy.fetch import PolicyFetchResult
from fnol_policy.service import PolicyError, run_policy


def start_policy(
    case_id: str | None = None,
    *,
    mock_url: str | None = None,
    state_dir_path: str | Path | None = None,
    fetch: Callable[..., PolicyFetchResult] | None = None,
) -> dict[str, Any]:
    """Select the policy version for one case, or for every case with an input revision."""
    mock_url = mock_url or os.environ.get("FNOL_MOCK_URL", "http://127.0.0.1:8767")
    directory = Path(state_dir_path) if state_dir_path is not None else state_dir()
    stores = Stores(directory)
    trace_id = uuid.uuid4().hex
    try:
        if case_id:
            case_ids = [case_id]
        else:
            case_ids = [row["case_id"] for row in stores.input.latest_loss_keys()]
            if not case_ids:
                raise PolicyError("no_cases", "input.sqlite has no revisions; run intake first")
        decisions = [run_policy(cid, stores, base_url=mock_url, fetch=fetch, trace_id=trace_id)
                     for cid in case_ids]
        return {
            "input_sqlite": str(stores.input.path.resolve()),
            "trace_sqlite": str(stores.trace.path.resolve()),
            "trace_id": trace_id,
            "case_count": len(decisions),
            "decisions": decisions,
        }
    finally:
        stores.close()
