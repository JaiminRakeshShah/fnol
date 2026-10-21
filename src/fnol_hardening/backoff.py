"""Exponential backoff with full jitter.

Delay after a failed attempt is drawn from Uniform(0, min(cap, base * 2^(attempt-1))).
Attempt 1 uses the base ceiling, attempt 2 doubles it, and so on.
"""

from __future__ import annotations

import random
import time

DEFAULT_BASE_SECONDS = 0.05
DEFAULT_CAP_SECONDS = 2.0


def backoff_seconds(
    attempt: int,
    *,
    base: float = DEFAULT_BASE_SECONDS,
    cap: float = DEFAULT_CAP_SECONDS,
    rng: random.Random | None = None,
) -> float:
    """Return the sleep after a failed attempt. ``attempt`` is 1-based."""
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    if base < 0 or cap < 0:
        raise ValueError("base and cap must be non-negative")
    ceiling = min(cap, base * (2 ** (attempt - 1)))
    draw = rng.random() if rng is not None else random.random()
    return ceiling * draw


def sleep_backoff(
    attempt: int,
    *,
    base: float = DEFAULT_BASE_SECONDS,
    cap: float = DEFAULT_CAP_SECONDS,
    rng: random.Random | None = None,
    sleeper=None,
) -> float:
    """Sleep the jittered delay and return the seconds actually requested."""
    delay = backoff_seconds(attempt, base=base, cap=cap, rng=rng)
    (sleeper or time.sleep)(delay)
    return delay
