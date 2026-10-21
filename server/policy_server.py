"""Policy MCP server (Step 2). Tool: select_policy.

Fetches GET /v1/cases/{case_id}/policy from the mock (at most three attempts), drops
private_token, stores the canonical snapshot in input.sqlite tool_payloads, appends one
trace event per attempt plus one for the decision, and returns only the version decision.

Run: uv run python server/policy_server.py
Env: FNOL_MOCK_URL (default http://127.0.0.1:8767), FNOL_STATE_DIR (default .state)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from fnol_policy.pipeline import start_policy  # noqa: E402

mcp = MCPServer("fnol-policy")


@mcp.tool()
def select_policy(case_id: str | None = None) -> dict:
    """Select the single policy version in force at each case's incident timestamp.

    The timestamp comes from the case's latest input revision, so run intake first.
    Omit case_id to process every ingested case. Each decision carries
    selected_policy_version (or null), reason (one | zero | multiple | wording_missing |
    unavailable | not_found), policy_ids, and identifiers for cross-checks.
    Never returns private_token or the full policies array.
    """
    return start_policy(case_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
