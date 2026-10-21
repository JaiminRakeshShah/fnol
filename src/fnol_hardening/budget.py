"""Error-budget policy for the FNOL triage SLO.

The SLO is 95% of cases triaged and routed within 15 seconds over a
rolling 28-day window. The budget is the other 5%. This helper says what
to do as that budget is consumed. It does not invent a traffic forecast;
the caller passes the observed case count.
"""

from __future__ import annotations

SLO_SUCCESS_RATIO = 0.95
WINDOW_DAYS = 28


def error_budget(*, cases: int, success_ratio: float = SLO_SUCCESS_RATIO) -> dict:
    """Return the allowed miss count for ``cases`` in one 28-day window."""
    if cases < 0:
        raise ValueError("cases must be non-negative")
    if not 0 <= success_ratio <= 1:
        raise ValueError("success_ratio must be between 0 and 1")
    # Integer basis points keep 2800 * 5% equal to 140, not a binary-float residue.
    basis_points = int(round((1.0 - success_ratio) * 10000))
    allowed = cases * basis_points / 10000
    return {
        "window_days": WINDOW_DAYS,
        "cases": cases,
        "slo_success_ratio": success_ratio,
        "allowed_misses": allowed,
        "allowed_misses_rounded_down": int(allowed),
        "daily_burn_if_spread_evenly": allowed / WINDOW_DAYS,
    }


def budget_status(*, cases: int, misses: int, day_of_window: int) -> dict:
    """Say whether to keep shipping, freeze changes, or fail closed.

    ``day_of_window`` is 1-based and at most 28. Half the budget spent
    before day 14 freezes non-reliability changes. A spent budget routes
    new cases to manual_review until the window rolls forward.
    """
    if day_of_window < 1 or day_of_window > WINDOW_DAYS:
        raise ValueError("day_of_window must be from 1 to 28")
    if misses < 0:
        raise ValueError("misses must be non-negative")
    budget = error_budget(cases=cases)
    allowed = budget["allowed_misses"]
    fraction = 0.0 if allowed == 0 else misses / allowed
    if allowed == 0:
        action = "fail_closed_manual_review" if misses else "nominal"
    elif fraction >= 1:
        action = "fail_closed_manual_review"
    elif fraction >= 0.5 and day_of_window <= 14:
        action = "freeze_non_reliability_changes"
    else:
        action = "nominal"
    return {
        **budget,
        "misses": misses,
        "day_of_window": day_of_window,
        "fraction_consumed": fraction,
        "action": action,
    }
