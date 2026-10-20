"""Canonical JSON and SHA-256 matching tools/runtime.py.

The mock hashes review drafts with sorted keys, no extra whitespace, and
UTF-8 characters left as themselves. Draft hashes only compare equal when
this helper uses that same form.
"""

import hashlib
import json

RESTRICTED_MARKERS = ("private_token", "SYNTHETIC-PRIVATE-")


def canonical(value):
    """Return the mock's canonical JSON form of value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    """Return the hex SHA-256 of canonical(value), matching tools.runtime.digest."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class RestrictedValueError(ValueError):
    """A stored value contained a restricted synthetic marker."""


def assert_no_restricted(value):
    """Refuse private_token and SYNTHETIC-PRIVATE- markers before persistence.

    The error does not echo the submitted value.
    """
    text = value if isinstance(value, str) else canonical(value)
    if any(marker in text for marker in RESTRICTED_MARKERS):
        raise RestrictedValueError("restricted value refused")
