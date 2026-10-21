"""Command line for the policy server."""
import argparse
import json

from fnol_policy.pipeline import start_policy
from fnol_policy.service import PolicyError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Select the policy version in force for each ingested case.")
    parser.add_argument("--mock-url", default=None, help="Defaults to FNOL_MOCK_URL or http://127.0.0.1:8767.")
    parser.add_argument("--state-dir", default=None, help="Directory for the SQLite files. Defaults to FNOL_STATE_DIR or .state.")
    parser.add_argument("--case-id", default=None, help="Optional. Omit to process every case with an input revision.")
    args = parser.parse_args(argv)
    try:
        result = start_policy(args.case_id, mock_url=args.mock_url, state_dir_path=args.state_dir)
    except PolicyError as exc:
        print(f"{exc.error_code}: {exc}")
        return 1
    for d in result["decisions"]:
        print(json.dumps({k: d.get(k) for k in ("case_id", "selected_policy_version", "reason", "policy_ids", "attempts")}))
    return 0
