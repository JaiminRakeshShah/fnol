"""Citations MCP server (Step 4). Tool: start_citations.

Slices exact quotes from the raw text and raw JSON already stored by intake,
policy, and rules. Refuses any quote containing private_token or
SYNTHETIC-PRIVATE-. Does not call the mock and does not store file text.

Run: uv run python server/citation_server.py
Env: FNOL_STATE_DIR (default .state), FNOL_POLICIES_DIR (default data/dev/policies)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from fnol_citations.pipeline import start_citations as cite_cases  # noqa: E402

mcp = MCPServer("fnol-citations")


@mcp.tool()
def start_citations(case_id: str | None = None) -> dict:
    """Slice exact evidence quotes for cases already ingested.

    Omit case_id to cite every case with an input revision. Each case returns
    policy_ids and citations (claim, source_id, quote). Claims quotes are
    omitted when the claims snapshot was not stored. Report and estimate quotes
    are included when those documents conflict with another source, and the
    estimate is always included when referral_indicator is repair_amount_conflict.
    Never returns private_token or SYNTHETIC-PRIVATE-.
    """
    return cite_cases(case_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
