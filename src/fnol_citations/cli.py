"""Command line for the citations server."""

import argparse
import json

from fnol_citations.pipeline import start_citations
from fnol_citations.service import CitationError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Slice exact evidence quotes for each ingested case.")
    parser.add_argument("--state-dir", default=None, help="Directory for the SQLite files. Defaults to FNOL_STATE_DIR or .state.")
    parser.add_argument("--policies-dir", default=None, help="Policy wording files. Defaults to FNOL_POLICIES_DIR or data/dev/policies.")
    parser.add_argument("--case-id", default=None, help="Optional. Omit to cite every case with an input revision.")
    args = parser.parse_args(argv)
    try:
        result = start_citations(args.case_id, state_dir_path=args.state_dir, policies_dir=args.policies_dir)
    except CitationError as exc:
        print(f"{exc.error_code}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0
