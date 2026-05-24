#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from integration_test import run_smoke_test


class IntegrationSmokeTest(unittest.TestCase):
    def test_run_smoke_test(self):
        result = run_smoke_test()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["steps"]), 7)
        self.assertTrue(all(step["status"] == "ok" for step in result["steps"]))


if __name__ == "__main__":
    unittest.main()
