"""Scan the tree and git history for hardcoded credentials.

Exit 0 when the working tree and commits since ``final`` are clean.
``--ancestors`` also reports matches in older history. Those are printed
and do not by themselves fail the default scan.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = (
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_temp_key", re.compile(r"ASIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
    ("aws_secret_access_key", re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{20,}['\"]")),
    (
        "quoted_api_key",
        re.compile(r"(?i)(?:api[_-]?key|apikey|api_secret)\s*[=:]\s*['\"][^'\"]{8,}['\"]"),
    ),
    ("bearer_token", re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{24,}")),
    ("quoted_password", re.compile(r"(?i)(?:password|passwd|secret)\s*[=:]\s*['\"][^'\"]{8,}['\"]")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("provider_secret", re.compile(r"sk-(?:live|proj|ant)-[A-Za-z0-9]{10,}")),
)

SKIP_DIRS = {".git", ".venv", ".state", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_SUFFIXES = {".png", ".pdf", ".sqlite", ".pyc", ".zip", ".woff", ".lock"}
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".example",
    ".env", ".cfg", ".ini", ".sh", ".html", ".css", ".js", ".ts",
}


class Finding:
    def __init__(self, scope, location, line, name):
        self.scope = scope
        self.location = location
        self.line = line
        self.name = name

    def __str__(self):
        return f"{self.scope}: {self.location}:{self.line}: {self.name}"


def _scan_text(scope, location, text):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in PATTERNS:
            if pattern.search(line):
                found.append(Finding(scope, location, number, name))
    return found


def _wanted(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {".env.example", ".gitignore"}


def scan_tree(root: Path = ROOT):
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or not _wanted(path.relative_to(root)):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.extend(_scan_text("tree", str(path.relative_to(root)), text))
    return found


def _git(*args):
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def scan_range(rev_range: str, scope: str):
    code, stdout, _stderr = _git("log", "--format=format:commit %H", "-p", rev_range)
    if code != 0 or not stdout.strip():
        return []
    found = []
    commit = "unknown"
    location = "diff"
    for line in stdout.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1][:12]
            continue
        if line.startswith("diff --git "):
            parts = line.split()
            location = parts[-1][2:] if len(parts) >= 4 else "diff"
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        for name, pattern in PATTERNS:
            if pattern.search(added):
                found.append(Finding(scope, f"{commit}:{location}", 0, name))
                break
    return found


def commits_since(base: str) -> str | None:
    code, stdout, _stderr = _git("rev-parse", "--verify", base)
    if code != 0:
        return None
    code, stdout, _stderr = _git("rev-list", "--count", f"{base}..HEAD")
    if code != 0:
        return None
    if stdout.strip() == "0":
        return None
    return f"{base}..HEAD"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scan for hardcoded credentials.")
    parser.add_argument("--ancestors", action="store_true", help="Also scan commits already on final.")
    parser.add_argument("--base", default="final")
    args = parser.parse_args(argv)

    tree = scan_tree()
    print(f"working tree findings: {len(tree)}")
    for item in tree:
        print(f"  {item}")

    rev_range = commits_since(args.base)
    if rev_range is None:
        branch = []
        print(f"commits since {args.base}: none")
    else:
        branch = scan_range(rev_range, "branch")
        print(f"commits since {args.base} findings: {len(branch)}")
        for item in branch:
            print(f"  {item}")

    if args.ancestors:
        ancestors = scan_range("HEAD", "ancestor")
        print(f"all reachable history findings: {len(ancestors)}")
        for item in ancestors:
            print(f"  {item}")

    if tree or branch:
        print("FAIL")
        return 1
    print("CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
