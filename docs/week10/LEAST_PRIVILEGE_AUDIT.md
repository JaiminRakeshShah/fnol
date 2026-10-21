# Least-privilege audit

The human boundary, from `BRIEF.md` and `AUTO-TRIAGE-01`: no final coverage, liability, fraud, reserve, settlement, denial, or payment decision. A referral indicator is not a fraud finding. Claim-record creation requires a human to approve that exact draft. The copilot must not invoke the operator approve command.

`authorize()` in `src/fnol_hardening/privilege.py` raises `PrivilegeError` for anything outside the allowlist. `FORBIDDEN_FOR_EVERYONE` cannot be performed by any actor, including the human operator role in this training system. Payment, denial, settlement, reserves, and adjudication are in that set.

`default_transport` in `src/fnol_analyst/http.py` calls `authorize_http` before it opens a socket. `AnalystClient._call_transport` does the same even when a test double replaces the socket. Tool reads go through `fetch_with_retries`, which allows only `read_policy` (policy component) and `read_claims` (rules component). Intake authorizes `read_health` and `read_case_list` before those GETs. Citations authorizes `read_stored_evidence` and `read_procedure` at the start of `run_citations`. Shadow authorizes `write_summary_slot` and refuses every mapped claims-mock action, including `POST /v1/payments`, before `urlopen`.

## Allowlist

| Component | May call | May not call |
|---|---|---|
| intake | `read_health`, `read_case_list`, `read_document` | writes, approval, payment |
| policy | `read_policy` | claims writes, approval, payment |
| rules | `read_claims` | record create, approval, payment |
| citations | `read_stored_evidence`, `read_procedure` | mock writes, approval, payment |
| analyst | read tools, `build_draft`, `submit_review`, `poll_review`, `file_record` | `approve_review`, `pay_claim`, `deny_claim`, adjudication |
| shadow | `read_packet`, `write_summary_slot` | tools that create or decide a claim |
| human_operator | `approve_review`, `reject_review`, `read_pending`, `read_audit`, `reset_mock_state` | `pay_claim` and every other forbidden decision |

`approve_review` is the operator CLI (`tools/runtime.py approve`). The analyst has no function that calls it. `file_record` only POSTs `/v1/records` after a human has approved the exact draft hash. A changed draft needs a new approval. The mock returns 403 if the hash does not match.

Tests in `tests/test_hardening.py` call `authorize("analyst", "pay_claim")` and `default_transport` against `POST /v1/payments` and assert `PrivilegeError` with no socket opened.
