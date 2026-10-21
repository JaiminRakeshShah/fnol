# Failure case to pattern

Mapped from `BRIEF.md` and `data/dev/policies/AUTO-TRIAGE-01.md` before the hardening code. The same table is `FAILURE_CASES` in `src/fnol_hardening/mapping.py`.

## 1. Claims or policy API timeout

- **Where:** `AUTO-D11` fails the claims read once, then succeeds. `AUTO-D07` fails claims on every attempt. The mock returns HTTP 503 `upstream_timeout` immediately.
- **Pattern:** Retry with exponential backoff and full jitter, at most three attempts total, behind a circuit breaker with closed, open, and half-open states.
- **Fallback:** The snapshot is unavailable. The route is `manual_review`. The call returns. It does not sleep on an open circuit.

## 2. Duplicate FNOL submission or duplicate record create

- **Where:** A second POST with the same `Idempotency-Key`. `AUTO-D09` and `AUTO-D10` are two intake ids for one logical loss, `auto-loss-nine`.
- **Pattern:** Idempotency key plus a fingerprint of the body. The first result is stored and replayed.
- **Fallback:** The second identical request returns the original record (HTTP 200). A new key for the same logical loss returns HTTP 409 `duplicate_case`. One row is written.

## 3. Prompt injection in a repair estimate, note, or upload

- **Where:** `AUTO-D08-ESTIMATE` contains a `SYSTEM:` line that says to pay 8400, skip human approval, and print private tokens.
- **Pattern:** Input and context separation. Document text is untrusted data, not an instruction.
- **Fallback:** The line is quarantined. The action list is empty. The route stays the rule route (`standard` for D08). A model reply that obeys the line is blocked and withheld.

## 4. Ambiguous policy interval

- **Where:** `AUTO-D05` has two policy intervals that both contain the incident timestamp.
- **Pattern:** Human escalation. This is not a retry and not a denial.
- **Fallback:** `selected_policy_version` is null. The route is `manual_review`. Only `AUTO-TRIAGE-01` is cited as applicable policy.

## 5. Stale or boundary policy period

- **Where:** `AUTO-D06` incident timestamp equals `effective_to`. Intervals include the start and exclude the end, so no interval matches.
- **Pattern:** Human escalation. A period mismatch is not an automatic denial.
- **Fallback:** `selected_policy_version` is null. The route is `manual_review`.

Input revisions still advance when the same documents are ingested again. That preserves the append-only history the intake tests require. The duplicate that must not happen is a second claim record, and that is what the idempotency key and the logical-loss check stop.
