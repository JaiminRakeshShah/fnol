"""Command line for the analyst client.

  ingest    step 1 through the intake server
  policy    step 2 through the policy server (optional --case-id)
  route     step 3 through the rules server (optional --case-id)
  cite      step 4 through the citations server (optional --case-id)
  prepare   steps 1-4, then build and export every draft
  build     steps 5 and 8 for one case or all cases
  export    write the contract JSON array
"""

from __future__ import annotations

import argparse
import json
import sys
from fnol_analyst.client import AnalystClient, AnalystError
from fnol_analyst.mcp import ServerError


def _print(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FNOL analyst client.")
    parser.add_argument("--mock-url", default=None)
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--documents-dir", default=None)
    parser.add_argument("--policies-dir", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest")
    policy = sub.add_parser("policy")
    policy.add_argument("--case-id", default=None)
    route = sub.add_parser("route")
    route.add_argument("--case-id", default=None)
    cite = sub.add_parser("cite")
    cite.add_argument("--case-id", default=None)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--out", default="submissions/results.json")
    prepare.add_argument("--workers", type=int, default=3)
    build = sub.add_parser("build")
    build.add_argument("--case-id", default=None)
    export = sub.add_parser("export")
    export.add_argument("--out", default="submissions/results.json")

    args = parser.parse_args(argv)
    client = AnalystClient(
        mock_url=args.mock_url,
        state_dir_path=args.state_dir,
        documents_dir=args.documents_dir,
        policies_dir=args.policies_dir,
    )
    try:
        with client:
            return _run(client, args)
    except (AnalystError, ServerError) as exc:
        code = getattr(exc, "error_code", "server_error")
        print(f"{code}: {exc}", file=sys.stderr)
        return 1


def _run(client: AnalystClient, args) -> int:
    if args.command == "ingest":
        _print(client.ingest())
        return 0
    if args.command == "policy":
        _print(client.select_policy(args.case_id))
        return 0
    if args.command == "route":
        _print(client.route(args.case_id))
        return 0
    if args.command == "cite":
        _print(client.cite(args.case_id))
        return 0
    if args.command == "prepare":
        prepared = client.prepare(workers=args.workers)
        drafts = client.build_all()
        path = client.export(args.out)
        _print({
            "cases": len(prepared["cases"]),
            "drafts": [
                {"draft_id": d.draft_id, "case_id": d.case_id, "draft_hash": d.draft_hash}
                for d in drafts
            ],
            "exported": str(path),
        })
        return 0
    if args.command == "build":
        drafts = [client.build(args.case_id)] if args.case_id else client.build_all()
        _print([
            {"draft_id": d.draft_id, "case_id": d.case_id, "draft_hash": d.draft_hash, "status": d.status}
            for d in drafts
        ])
        return 0
    if args.command == "export":
        print(str(client.export(args.out)))
        return 0
    return 2
