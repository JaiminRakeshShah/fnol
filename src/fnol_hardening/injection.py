"""Separate untrusted document text from instructions.

Repair estimates, prior notes, and uploaded files are data. A line that
tries to change the agent's role, skip human approval, pay a claim, or
print a restricted token is quarantined. It is never returned as an
action and it does not change the route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Instruction-shaped lines. These are matched only so they can be quoted
# back as data. Matching does not execute them.
_INSTRUCTION = re.compile(
    r"(?i)(?:"
    r"^\s*system\s*:"
    r"|^\s*ignore\s+(?:all|any|previous|prior)"
    r"|you\s+are\s+now\b"
    r"|ignore\s+(?:any\s+|the\s+)?human[- ]approval"
    r"|print\s+all\s+private\s+tokens"
    r"|pay\s+\d+"
    r"|\bclaim\s+is\s+covered\b"
    r"|settlement\s+approver"
    r")"
)


@dataclass(frozen=True)
class UntrustedSplit:
    evidence_lines: tuple[str, ...]
    quarantined_lines: tuple[str, ...]

    @property
    def injection_detected(self) -> bool:
        return bool(self.quarantined_lines)


def split_untrusted(text: str) -> UntrustedSplit:
    """Split one document into evidence lines and quarantined instruction lines."""
    if not isinstance(text, str):
        raise TypeError("document text must be a string")
    evidence: list[str] = []
    quarantined: list[str] = []
    for line in text.splitlines():
        if _INSTRUCTION.search(line):
            quarantined.append(line)
        else:
            evidence.append(line)
    return UntrustedSplit(tuple(evidence), tuple(quarantined))


def actions_from_untrusted(text: str) -> list[dict]:
    """Untrusted text never becomes a tool call. The action list is empty."""
    split_untrusted(text)
    return []


def handling_report(text: str, *, source_id: str, route: str | None = None) -> dict:
    """Describe how the copilot treats one untrusted document.

    ``actions`` is always empty. ``route_changed`` is always false.
    The quarantined lines are echoed as data so an operator can see the
    injection without the system obeying it.
    """
    split = split_untrusted(text)
    return {
        "source_id": source_id,
        "treated_as": "untrusted_data",
        "instructions_followed": False,
        "actions": actions_from_untrusted(text),
        "route_changed": False,
        "route": route,
        "injection_detected": split.injection_detected,
        "quarantined": list(split.quarantined_lines),
        "response": (
            "Quarantined embedded instructions as untrusted evidence. "
            "No coverage, payment, approval, or token disclosure was performed."
            if split.injection_detected
            else "No embedded instruction detected. Document used only as evidence."
        ),
    }
