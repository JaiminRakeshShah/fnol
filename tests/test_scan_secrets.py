"""The working tree has no hardcoded credentials."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.scan_secrets import scan_tree  # noqa: E402


class SecretScanTests(unittest.TestCase):
    def test_working_tree_is_clean(self):
        found = scan_tree(ROOT)
        self.assertEqual(found, [], [str(item) for item in found])
