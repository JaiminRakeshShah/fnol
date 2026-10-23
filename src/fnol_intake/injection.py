"""Deterministic extra-field check on supplied documents.

A ``Label: value`` line whose label is not a known label for that document is
an extra field. Intake stores those labels on the immutable revision. The
model screen of the labels and leftover lines runs later, on the rules service,
so a model outage cannot block the revision.
"""

from __future__ import annotations

from fnol_foundation.canonical import RESTRICTED_MARKERS

CLEAN = "clean"
INJECTION = "injection"
ERROR = "error"

RESTRICTED_LABEL = "restricted_label"


def _header(line):
    return not line.strip() or line.startswith("#") or line.startswith("Source ID:")


def _restricted(text):
    return any(marker in text for marker in RESTRICTED_MARKERS)


def extra_fields(text, labels):
    """Labels of ``Label: value`` lines that are not in this document's label map."""
    found = []
    for line in text.splitlines():
        if _header(line):
            continue
        key, sep, _value = line.partition(": ")
        if sep and key not in labels:
            found.append(RESTRICTED_LABEL if _restricted(key) else key)
    return found


def field_status(items):
    return INJECTION if items else CLEAN
