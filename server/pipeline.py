"""One-call intake pipeline. The MCP tool and any local caller share this entry."""

import os
from pathlib import Path

from fnol_foundation.stores import Stores, state_dir
from fnol_intake.run import run_intake

ROOT = Path(__file__).resolve().parents[1]


def apply_duplicate_flags(payloads, existing):
    """Mark a case when another case_id shares its loss_reference."""
    groups = {}
    for row in list(existing) + list(payloads):
        ref = row.get("loss_reference")
        case_id = row.get("case_id")
        if ref and case_id:
            groups.setdefault(ref, set()).add(case_id)
    for payload in payloads:
        ref = payload.get("loss_reference")
        matches = groups.get(ref, set()) if ref else set()
        payload["duplicates"] = 1 if len(matches) > 1 else 0


def start_ingestion(mock_url=None, documents_dir=None, policies_dir=None, state_dir_path=None, transport=None):
    """Read the mock case list and write input.sqlite. Returns the file path and case rows."""
    mock_url = mock_url or os.environ.get("FNOL_MOCK_URL", "http://127.0.0.1:8767")
    documents = Path(documents_dir or os.environ.get("FNOL_DOCUMENTS_DIR", ROOT / "data" / "dev" / "documents"))
    policies = Path(policies_dir or os.environ.get("FNOL_POLICIES_DIR", ROOT / "data" / "dev" / "policies"))
    directory = Path(state_dir_path) if state_dir_path is not None else state_dir()
    stores = Stores(directory)
    try:
        result = run_intake(stores, mock_url, documents, policies, transport=transport)
    finally:
        stores.close()
    return {
        "input_sqlite": str(stores.input.path.resolve()),
        "case_count": len(result["revisions"]),
        "duplicate_count": sum(1 for revision in result["revisions"] if revision.payload.get("duplicates") == 1),
        "revisions": [
            {"case_id": revision.case_id, "revision": revision.revision}
            for revision in result["revisions"]
        ],
    }
