"""The four step servers as one set the analyst can call independently or in sequence."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fnol_analyst.mcp import StdioServer

ROOT = Path(__file__).resolve().parents[2]

SERVER_FILES = {
    "intake": "server/input_server.py",
    "policy": "server/policy_server.py",
    "rules": "server/rules_server.py",
    "citations": "server/citation_server.py",
}
TOOLS = {
    "intake": "start_ingestion",
    "policy": "start_policy",
    "rules": "start_routing",
    "citations": "start_citations",
}


class ServerSet:
    """Spawns the four stdio servers with a shared state directory and mock URL."""

    def __init__(
        self,
        *,
        state_dir: Path,
        mock_url: str,
        documents_dir: Path | None = None,
        policies_dir: Path | None = None,
        python: str | None = None,
    ):
        env = dict(os.environ)
        env["FNOL_STATE_DIR"] = str(state_dir)
        env["FNOL_MOCK_URL"] = mock_url
        if documents_dir is not None:
            env["FNOL_DOCUMENTS_DIR"] = str(documents_dir)
        if policies_dir is not None:
            env["FNOL_POLICIES_DIR"] = str(policies_dir)
        interpreter = python or sys.executable
        self.servers: dict[str, StdioServer] = {
            name: StdioServer(name, [interpreter, str(ROOT / path)], cwd=str(ROOT), env=env)
            for name, path in SERVER_FILES.items()
        }

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self) -> None:
        for server in self.servers.values():
            server.close()

    def call(self, step: str, case_id: str | None = None) -> dict[str, Any]:
        """Call one step server. intake takes no case id; the others accept one."""
        if step not in TOOLS:
            raise KeyError(step)
        arguments = {} if step == "intake" or case_id is None else {"case_id": case_id}
        return self.servers[step].call(TOOLS[step], arguments)

    def ingest(self) -> dict[str, Any]:
        return self.call("intake")

    def select_policy(self, case_id: str | None = None) -> dict[str, Any]:
        return self.call("policy", case_id)

    def route(self, case_id: str | None = None) -> dict[str, Any]:
        return self.call("rules", case_id)

    def cite(self, case_id: str | None = None) -> dict[str, Any]:
        return self.call("citations", case_id)

    def prepare_case(self, case_id: str) -> dict[str, Any]:
        """Policy, then rules, then citations for one already-ingested case.

        Those three steps share one revision and must stay in order. Across
        cases they overlap: one case can sit in policy while another is in
        rules and a third is in citations.
        """
        policy = self.select_policy(case_id)["policies"][0]
        route = self.route(case_id)["routes"][0]
        cited = self.cite(case_id)["cases"][0]
        return {"case_id": case_id, "policy": policy, "route": route, "citations": cited}

    def prepare_all(self, case_ids: list[str], *, workers: int = 3) -> dict[str, dict[str, Any]]:
        """Run prepare_case for many cases. Each server still handles one call at a time."""
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for case_id, result in zip(case_ids, pool.map(self.prepare_case, case_ids)):
                results[case_id] = result
        return results
