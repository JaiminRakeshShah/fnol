"""SLO metrics: route success ratio and time-to-route p95.

A sample counts as a success when a route was produced within the SLO
latency (15 seconds), including an honest manual_review. The page fires
when the success ratio drops below 95% after at least 20 samples, or when
p95 time-to-route exceeds 15 seconds.
"""

from __future__ import annotations

import math
import threading

SLO_LATENCY_MS = 15_000
SLO_SUCCESS_RATIO = 0.95
PAGE_MIN_SAMPLES = 20


class RouteMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._durations: list[int] = []
        self._successes = 0

    def reset(self) -> None:
        with self._lock:
            self._durations.clear()
            self._successes = 0

    def observe_route(self, duration_ms: int, *, routed: bool) -> None:
        if duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        with self._lock:
            self._durations.append(int(duration_ms))
            if routed and duration_ms <= SLO_LATENCY_MS:
                self._successes += 1

    def success_ratio(self) -> float | None:
        with self._lock:
            if not self._durations:
                return None
            return self._successes / len(self._durations)

    def p95_ms(self) -> float | None:
        with self._lock:
            if not self._durations:
                return None
            ordered = sorted(self._durations)
            index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
            return float(ordered[index])

    def sample_count(self) -> int:
        with self._lock:
            return len(self._durations)

    def alert(self) -> dict:
        """Page a human when the SLO is breached on a large enough window."""
        ratio = self.success_ratio()
        p95 = self.p95_ms()
        count = self.sample_count()
        reasons = []
        if count >= PAGE_MIN_SAMPLES and ratio is not None and ratio < SLO_SUCCESS_RATIO:
            reasons.append(
                f"route_within_slo_ratio {ratio:.4f} < {SLO_SUCCESS_RATIO:.2f} over {count} samples"
            )
        if count >= PAGE_MIN_SAMPLES and p95 is not None and p95 > SLO_LATENCY_MS:
            reasons.append(f"time_to_route_p95_ms {p95:.0f} > {SLO_LATENCY_MS}")
        return {
            "name": "fnol_slo_breach",
            "page": bool(reasons),
            "severity": "page" if reasons else "ok",
            "reasons": reasons,
            "route_within_slo_ratio": ratio,
            "time_to_route_p95_ms": p95,
            "samples": count,
            "threshold": {
                "min_samples": PAGE_MIN_SAMPLES,
                "success_ratio_below": SLO_SUCCESS_RATIO,
                "p95_ms_above": SLO_LATENCY_MS,
            },
        }

    def snapshot(self) -> dict:
        alert = self.alert()
        return {
            "route_within_slo_ratio": alert["route_within_slo_ratio"],
            "time_to_route_p95_ms": alert["time_to_route_p95_ms"],
            "samples": alert["samples"],
            "alert": alert,
        }


metrics = RouteMetrics()
