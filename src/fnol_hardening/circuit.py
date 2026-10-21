"""Circuit breaker with closed, open, and half-open states.

A dependency that fails ``failure_threshold`` times in a row opens. While
open, calls fail immediately. After ``recovery_seconds`` the next call is a
single half-open trial. Success closes the breaker. Failure opens it again.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable


class CircuitOpenError(RuntimeError):
    def __init__(self, name: str):
        super().__init__(f"circuit {name} is open")
        self.name = name
        self.error_code = "circuit_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 8,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_seconds < 0:
            raise ValueError("recovery_seconds must be non-negative")
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self._half_open_inflight = False

    def before_call(self) -> str:
        """Return the state the call is allowed to run in, or raise if open."""
        with self._lock:
            if self.state == "open":
                if self._clock() - self.opened_at >= self.recovery_seconds:
                    self.state = "half_open"
                    self._half_open_inflight = False
                else:
                    raise CircuitOpenError(self.name)
            if self.state == "half_open":
                if self._half_open_inflight:
                    raise CircuitOpenError(self.name)
                self._half_open_inflight = True
            return self.state

    def record_success(self) -> str:
        with self._lock:
            self.failures = 0
            self.state = "closed"
            self._half_open_inflight = False
            return self.state

    def record_failure(self) -> str:
        with self._lock:
            self.failures += 1
            self._half_open_inflight = False
            if self.state == "half_open" or self.failures >= self.failure_threshold:
                self.state = "open"
                self.opened_at = self._clock()
            return self.state

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state,
                "failures": self.failures,
                "failure_threshold": self.failure_threshold,
                "recovery_seconds": self.recovery_seconds,
            }


_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def _threshold() -> int:
    raw = os.environ.get("FNOL_CIRCUIT_FAILURE_THRESHOLD", "8")
    try:
        value = int(raw)
    except ValueError:
        return 8
    return value if value >= 1 else 8


def _recovery() -> float:
    raw = os.environ.get("FNOL_CIRCUIT_RECOVERY_SECONDS", "30")
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    return value if value >= 0 else 30.0


def breaker_for(name: str) -> CircuitBreaker:
    """Return the process-wide breaker for one dependency name."""
    with _registry_lock:
        breaker = _registry.get(name)
        if breaker is None:
            breaker = CircuitBreaker(
                name,
                failure_threshold=_threshold(),
                recovery_seconds=_recovery(),
            )
            _registry[name] = breaker
        return breaker


def reset_breakers() -> None:
    with _registry_lock:
        _registry.clear()


def dependency_name(url: str) -> str:
    """Map a tool URL onto the dependency the breaker protects."""
    path = url.split("?", 1)[0].rstrip("/")
    if path.endswith("/claims"):
        return "claims"
    if path.endswith("/policy"):
        return "policy"
    if path.endswith("/health") or path.endswith("/v1/cases"):
        return "case_list"
    host = ""
    if "://" in url:
        host = url.split("://", 1)[1].split("/", 1)[0]
    return host or "unknown"
