"""Render the Week 10 lab PDF from real source files and demo output.

Pillow and fpdf2 are used only for this rendering step. The copilot itself
stays on the Python standard library.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "week10"
EVIDENCE = DOCS / "evidence"
SHOTS = DOCS / "screenshots"
PDF_PATH = DOCS / "Week10_Lab_Hardening.pdf"

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Image is scaled to 576pt on a letter page. 26px on a 900px image is about
# 17pt on the page. MAX_LINES keeps a full page under the letter height.
WIDTH = 900
MARGIN = 28
BODY = 26
TITLE = 28
LINE = 34
MAX_LINES = 26


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap_text(text, face, width):
    if text == "":
        return [""]
    if face.getlength(text) <= width:
        return [text]
    lines = []
    current = ""
    tokens = text.split(" ")
    for token in tokens:
        pieces = _break_token(token, face, width)
        for index, piece in enumerate(pieces):
            joiner = "" if (index or not current) else " "
            trial = piece if not current else current + joiner + piece
            if face.getlength(trial) <= width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = piece
    if current:
        lines.append(current)
    return lines or [""]


def _break_token(token, face, width):
    if face.getlength(token) <= width:
        return [token]
    pieces = []
    buf = ""
    for char in token:
        trial = buf + char
        if face.getlength(trial) <= width:
            buf = trial
        else:
            if buf:
                pieces.append(buf)
            buf = char
    if buf:
        pieces.append(buf)
    return pieces


def block(path, start_marker, end_marker=None):
    """Return numbered source lines from start_marker through the line before end_marker."""
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if start_marker in line)
    while start > 0 and lines[start - 1].lstrip().startswith("@"):
        start -= 1
    end = len(lines)
    if end_marker:
        for index in range(start + 1, len(lines)):
            if end_marker in lines[index]:
                end = index
                break
    numbered = []
    for offset, text in enumerate(lines[start:end]):
        numbered.append(f"{start + offset + 1:4d} | {text}")
    return numbered


def pages_for(title, body_lines, *, theme, mono=True):
    face = font(MONO if mono else SANS, BODY)
    bold = font(MONO_BOLD if mono else SANS_BOLD, TITLE)
    title_face = font(SANS_BOLD, TITLE)
    content_width = WIDTH - MARGIN * 2
    wrapped = []
    for line in body_lines:
        wrapped.extend(wrap_text(line.rstrip("\n"), face, content_width))
    if not wrapped:
        wrapped = [""]
    chunks = [wrapped[index:index + MAX_LINES] for index in range(0, len(wrapped), MAX_LINES)]
    images = []
    colors = {
        "doc": ("#f7f4ee", "#1c1917", "#1e3a5f", "#ffffff"),
        "code": ("#f8fafc", "#0f172a", "#1e293b", "#f8fafc"),
        "term": ("#0b1220", "#e5e7eb", "#111827", "#86efac"),
    }[theme]
    background, foreground, bar, bar_text = colors
    for chunk_index, chunk in enumerate(chunks):
        height = 78 + LINE * len(chunk) + 28
        image = Image.new("RGB", (WIDTH, height), background)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, WIDTH, 64), fill=bar)
        heading = title if chunk_index == 0 else f"{title} (continued)"
        draw.text((MARGIN, 16), heading, font=title_face, fill=bar_text)
        y = 78
        for line in chunk:
            draw.text((MARGIN, y), line, font=face, fill=foreground)
            y += LINE
        images.append(image)
    return images


def prose(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    lines = []
    for raw in text.splitlines():
        if raw.startswith("# "):
            lines.append("")
            lines.append(raw[2:].upper())
            lines.append("")
        elif raw.startswith("## "):
            lines.append("")
            lines.append(raw[3:])
            lines.append("")
        elif raw.startswith("- "):
            lines.append("  • " + raw[2:])
        else:
            lines.append(raw)
    return lines


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    for old in SHOTS.glob("*.png"):
        old.unlink()

    sections = [
        ("01 SLO and error budget", prose("docs/week10/SLO.md"), "doc", False),
        ("01 SLO numbers from the demo", (EVIDENCE / "01_slo.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("02 Failure-case to pattern mapping", prose("docs/week10/FAILURE_MAPPING.md"), "doc", False),
        ("02 Mapping as executed", (EVIDENCE / "02_failure_mapping.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("03 Retry, backoff, and circuit breaker", block(
            "src/fnol_hardening/circuit.py", "class CircuitOpenError", "_registry"
        ), "code", True),
        ("03 fetch_with_retries", block(
            "src/fnol_foundation/http.py", "def fetch_with_retries", "def _authorize_tool_read"
        ), "code", True),
        ("03 Backoff schedule", block(
            "src/fnol_hardening/backoff.py", "def backoff_seconds", "def sleep_backoff"
        ), "code", True),
        ("03 Terminal: recovery from a simulated timeout", (EVIDENCE / "03_timeout.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("04 Idempotency store", block(
            "src/fnol_hardening/idempotency.py", "class IdempotencyStore", "def fingerprint"
        ), "code", True),
        ("04 Record create replays a stored success", block(
            "src/fnol_analyst/submit.py", "store = _idempotency_store", "if post_status == 403"
        ), "code", True),
        ("04 Terminal: duplicate request", (EVIDENCE / "04_idempotency.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("05 Prompt injection is untrusted data", block(
            "src/fnol_hardening/injection.py", "class UntrustedSplit", None
        ), "code", True),
        ("05 Quarantine during draft build", block(
            "src/fnol_analyst/client.py", "def _quarantine_untrusted", "def _fill_evidence_summary"
        ), "code", True),
        ("05 Terminal: injected content and the response", (EVIDENCE / "05_injection.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("06 Least privilege", prose("docs/week10/LEAST_PRIVILEGE_AUDIT.md"), "doc", False),
        ("06 Guard that raises", block(
            "src/fnol_hardening/privilege.py", "FORBIDDEN_FOR_EVERYONE", "def action_for_http"
        ), "code", True),
        ("06 Terminal: human boundary enforced", (EVIDENCE / "06_privilege.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("07 No hardcoded credentials", (EVIDENCE / "07_secrets.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("07 Scanner patterns", block(
            "tools/scan_secrets.py", "PATTERNS =", "SKIP_DIRS"
        ), "code", True),
        ("08 Structured logging and tracing", block(
            "src/fnol_hardening/telemetry.py", "def log_span", "def _write"
        ), "code", True),
        ("08 Every pipeline event writes a span", block(
            "src/fnol_foundation/events.py", "def record_event", "return fields"
        ), "code", True),
        ("08 Sample trace from the scenario run", (EVIDENCE / "08_trace.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("09 Metrics and alert threshold", prose("docs/week10/METRICS_ALERTS.md"), "doc", False),
        ("09 alert() implementation", block(
            "src/fnol_hardening/metrics.py", "def alert", "def snapshot"
        ), "code", True),
        ("09 Terminal: metrics and the page", (EVIDENCE / "09_metrics.txt").read_text(encoding="utf-8").splitlines(), "term", True),
        ("10 Runbook: prompt injection", prose("docs/week10/RUNBOOK.md"), "doc", False),
        ("11 Three scenarios", (EVIDENCE / "11_scenarios.txt").read_text(encoding="utf-8").splitlines(), "term", True),
    ]

    saved = []
    for title, lines, theme, mono in sections:
        images = pages_for(title, lines, theme=theme, mono=mono)
        for index, image in enumerate(images, 1):
            slug = "".join(char.lower() if char.isalnum() else "-" for char in title).strip("-")
            while "--" in slug:
                slug = slug.replace("--", "-")
            path = SHOTS / f"{slug}-{index:02d}.png"
            image.save(path, format="PNG")
            saved.append(path)

    pdf = FPDF(format="letter", unit="pt")
    pdf.set_auto_page_break(auto=False)
    for path in saved:
        pdf.add_page()
        pdf.image(str(path), x=18, y=18, w=576)
    pdf.output(str(PDF_PATH))
    print(f"wrote {len(saved)} screenshots and {PDF_PATH}")


if __name__ == "__main__":
    sys.exit(main())
