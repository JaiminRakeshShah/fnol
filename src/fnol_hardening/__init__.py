"""Week-10 hardening for the Auto FNOL triage copilot.

Reliability, idempotency, untrusted-input separation, least privilege,
and structured traces live here and are called from the existing pipeline.
"""

__all__ = ["backoff", "budget", "circuit", "idempotency", "injection", "metrics", "privilege", "telemetry"]
