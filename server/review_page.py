"""One page for a human to accept or reject pending drafts."""

from __future__ import annotations

import json

from fnol_foundation.db import open_db
from fnol_foundation.stores import state_dir

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FNOL reviewer</title>
<style>
  body { font-family: sans-serif; margin: 24px; color: #1a1a1a; background: #f6f6f4; }
  h1 { font-size: 22px; font-weight: 600; }
  label { display: block; margin: 12px 0 4px; }
  input { font: inherit; padding: 6px 8px; width: 240px; }
  article { background: #fff; border: 1px solid #ccc; padding: 16px; margin: 16px 0; }
  .row { display: flex; gap: 8px; margin-top: 12px; }
  button { font: inherit; padding: 6px 12px; }
  pre { white-space: pre-wrap; background: #f0f0ec; padding: 8px; }
  .meta { color: #444; }
</style>
</head>
<body>
<h1>Pending cases</h1>
<label for="name">Reviewer name</label>
<input id="name" value="">
<div id="list">Loading…</div>
<script>
const headers = () => ({
  "Content-Type": "application/json",
  "X-Fnol-Roles": "Claims.Reviewer",
  "X-Fnol-Reviewer": document.getElementById("name").value.trim() || "reviewer"
});
function block(title, text) {
  return "<h3>" + title + "</h3><pre>" + (text || "None yet.") + "</pre>";
}
async function load() {
  const response = await fetch("/v1/queue", { headers: headers() });
  const rows = await response.json();
  const root = document.getElementById("list");
  root.innerHTML = "";
  if (!rows.length) {
    root.textContent = "No cases.";
    return;
  }
  for (const row of rows) {
    const card = document.createElement("article");
    const pending = row.status === "pending";
    card.innerHTML =
      "<h2>" + row.case_id + "</h2>" +
      "<p class='meta'>Review " + row.review_id + " · " + row.status +
      (row.reviewer ? " · " + row.reviewer : "") +
      (row.draft_status ? " · draft " + row.draft_status : "") +
      (row.outcome ? " · " + row.outcome : "") + "</p>" +
      "<p class='meta'>" + (row.classification || "—") + " · " + (row.routing || "—") + "</p>" +
      block("Deterministic draft", row.narrative) +
      block("Gemma summary", row.shadow_narrative) +
      (pending ? "<div class='row'><button data-act='approve'>Accept</button><button data-act='reject'>Reject</button></div>" : "");
    if (pending) {
      card.querySelectorAll("button").forEach((button) => {
        button.onclick = async () => {
          const name = document.getElementById("name").value.trim();
          if (!name) { alert("Enter your name first."); return; }
          button.disabled = true;
          await fetch("/v1/" + button.dataset.act + "/" + row.review_id, { method: "POST", headers: headers() });
          load();
        };
      });
    }
    root.appendChild(card);
  }
}
load();
</script>
</body>
</html>
"""


def _text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _draft_fields(case_id: str) -> dict:
    anchor = state_dir()
    found = {
        "narrative": None,
        "classification": None,
        "routing": None,
        "draft_status": None,
        "outcome": None,
        "shadow_narrative": None,
    }
    try:
        with open_db(anchor / "output.sqlite", kind="output") as db:
            row = db.execute(
                """SELECT draft_json, status, outcome FROM drafts
                   WHERE case_id = ? ORDER BY created_at DESC LIMIT 1""",
                (case_id,),
            ).fetchone()
        if row is not None:
            body = json.loads(row["draft_json"])
            found["narrative"] = _text(body.get("narrative"))
            found["classification"] = _text(body.get("classification"))
            found["routing"] = _text(body.get("routing"))
            found["draft_status"] = row["status"]
            found["outcome"] = row["outcome"]
    except Exception:
        pass
    try:
        with open_db(anchor / "trace.sqlite", kind="trace") as db:
            row = db.execute(
                """SELECT shadow_narrative FROM trace_events
                   WHERE case_id = ? AND shadow_narrative IS NOT NULL
                   ORDER BY started_at DESC LIMIT 1""",
                (case_id,),
            ).fetchone()
        if row is not None:
            found["shadow_narrative"] = _text(row["shadow_narrative"])
    except Exception:
        pass
    return found


def queue_rows(db) -> list[dict]:
    """Every review, newest first, with the draft and the Gemma paragraph."""
    reviews = db.execute(
        "SELECT id, case_id, status, reviewer FROM reviews ORDER BY id"
    ).fetchall()
    rows = []
    for review in reviews:
        item = {
            "review_id": review["id"],
            "case_id": review["case_id"],
            "status": review["status"],
            "reviewer": review["reviewer"],
        }
        item.update(_draft_fields(review["case_id"]))
        rows.append(item)
    return rows
