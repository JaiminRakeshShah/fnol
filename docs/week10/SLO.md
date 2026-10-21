# SLO and error budget

**SLO:** 95% of FNOL cases are triaged and routed within 15 seconds, measured over a rolling 28-day window.

A case counts as a success when the copilot returns a route (`standard`, `urgent`, `specialist`, or `manual_review`) within 15 seconds. An honest escalation is a success. A crash, a hang, or a route that arrives after 15 seconds is a miss.

## Error budget

The budget is the other 5% of cases in that window.

Worked example, 100 cases per day:

| Quantity | Value |
|---|---|
| Window | 28 days |
| Cases | 2,800 |
| Allowed misses | 140 |
| Even daily burn | 5 misses per day |

`error_budget(cases=2800)` in `src/fnol_hardening/budget.py` returns these numbers. The miss ratio is computed in basis points so 2,800 × 5% is 140, not a binary-float residue.

## When the budget is close to gone

`budget_status` returns one action:

- **Nominal.** Misses stay under half the budget, or half the budget is reached only after day 14. Keep the current release pace. Watch `fnol_slo_breach`.
- **Freeze non-reliability changes.** Half the budget (70 misses in the example) is gone on or before day 14. Ship only fixes for latency, retries, or the dependency that is burning the budget.
- **Fail closed.** The budget is spent (140 misses). New cases route `manual_review`. Automated record filing stops until the 28-day window rolls forward and the ratio is back inside the SLO. A human still reviews the queue. The copilot does not pay, deny, or approve a claim to catch up.

The page that fires before the budget is exhausted is `fnol_slo_breach`: page a human when, over at least 20 samples, the within-SLO ratio drops below 95% or the p95 time-to-route exceeds 15 seconds.
