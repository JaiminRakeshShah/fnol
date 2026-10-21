"""Deliberate failure cases from BRIEF.md and AUTO-TRIAGE-01, and the pattern that handles each one."""

FAILURE_CASES = (
    {
        "failure": "Claims or policy API timeout",
        "where": "AUTO-D11 fails claims once then succeeds. AUTO-D07 fails claims on every attempt. The mock returns 503 upstream_timeout.",
        "pattern": "Retry with exponential backoff and full jitter, at most three attempts, behind a circuit breaker (closed, open, half-open).",
        "fallback": "Claims or policy stay unavailable. Routing is manual_review. The call returns; it does not hang.",
    },
    {
        "failure": "Duplicate FNOL submission or duplicate record create",
        "where": "A second request with the same Idempotency-Key. AUTO-D09 and AUTO-D10 share logical loss auto-loss-nine.",
        "pattern": "Idempotency key plus body fingerprint. The original result is replayed.",
        "fallback": "No second claim record. A different body for the same key is a conflict. A second intake id for the same loss returns duplicate_case.",
    },
    {
        "failure": "Prompt injection in a repair estimate, note, or upload",
        "where": "AUTO-D08-ESTIMATE contains a SYSTEM line that demands payment, skips human approval, and asks for private tokens.",
        "pattern": "Input and context separation. Document text is untrusted data, not an instruction.",
        "fallback": "The line is quarantined. Actions taken: none. The route stays the rule route. A model reply that obeys the line is blocked.",
    },
    {
        "failure": "Ambiguous policy interval",
        "where": "AUTO-D05 has two policy intervals that both contain the incident timestamp.",
        "pattern": "Human escalation. This is not retried and not denied.",
        "fallback": "selected_policy_version is null. Route is manual_review. Only AUTO-TRIAGE-01 is cited as policy.",
    },
    {
        "failure": "Stale or boundary policy period",
        "where": "AUTO-D06 incident timestamp is exactly effective_to. Intervals exclude the end.",
        "pattern": "Human escalation. A period mismatch is not an automatic denial.",
        "fallback": "selected_policy_version is null. Route is manual_review.",
    },
)
