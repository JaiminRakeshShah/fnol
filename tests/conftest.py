"""Pytest defaults for the hardening suite.

Structured logs stay off stderr during tests so assertion output stays readable.
The demo process turns them on. The test API key is generated per process and
is not a credential.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("FNOL_LOG_STDERR", "0")
os.environ.setdefault("FNOL_TEST_API_KEY", "k" + format(os.getpid(), "x"))


@pytest.fixture(autouse=True)
def _reset_hardening_state():
    from fnol_hardening.circuit import reset_breakers
    from fnol_hardening.metrics import metrics

    reset_breakers()
    metrics.reset()
    yield
    reset_breakers()
    metrics.reset()
