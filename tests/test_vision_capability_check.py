import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

MODULE_PATH = ROOT / "scripts" / "vision_capability_check.py"
SPEC = importlib.util.spec_from_file_location("vc", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

check = MODULE.check
require = MODULE.require
VisionNotSupportedError = MODULE.VisionNotSupportedError


class TestVisionCapabilityCheck(unittest.TestCase):
    # ── Known vision-capable models ─────────────────────────────────────────

    def test_gpt_4o_is_supported(self):
        r = check("gpt-4o")
        self.assertTrue(r.supported)
        self.assertEqual(r.model_id, "gpt-4o")

    def test_claude_3_sonnet_is_supported(self):
        r = check("claude-3.5-sonnet-20250620")
        self.assertTrue(r.supported)

    def test_claude_haiku_is_supported(self):
        r = check("claude-3-haiku-20250707")
        self.assertTrue(r.supported)

    def test_gemini_1_5_is_supported(self):
        r = check("gemini-1.5-pro-preview-06-05")
        self.assertTrue(r.supported)

    def test_gemini_2_is_supported(self):
        r = check("gemini-2.0-flash-exp")
        self.assertTrue(r.supported)

    def test_vision_substring_in_model_id_is_supported(self):
        r = check("my-custom-gpt-4o-finetuned-vision-model")
        self.assertTrue(r.supported)

    # ── Known non-vision models ──────────────────────────────────────────────

    def test_gpt_3_5_not_supported(self):
        r = check("gpt-3.5-turbo-0125")
        self.assertFalse(r.supported)
        self.assertIsNotNone(r.fallback_message)

    def test_o3_not_supported(self):
        r = check("o3")
        self.assertFalse(r.supported)

    def test_gpt_4o_mini_not_supported(self):
        r = check("gpt-4o-mini-20250718")
        self.assertFalse(r.supported)

    # ── Unknown models (conservative: not supported) ─────────────────────────

    def test_unknown_model_not_supported(self):
        r = check("some-unknown-model-v1")
        self.assertFalse(r.supported)
        self.assertEqual(r.confidence, 0.5)  # uncertain

    def test_empty_model_returns_unknown(self):
        r = check(None)
        self.assertFalse(r.supported)
        self.assertEqual(r.model_id, "unknown")

    # ── require() raises ─────────────────────────────────────────────────────

    def test_require_raises_when_not_supported(self):
        with self.assertRaises(VisionNotSupportedError) as ctx:
            require("gpt-3.5-turbo")
        self.assertIn("gpt-3.5-turbo", str(ctx.exception))

    def test_require_does_not_raise_for_supported(self):
        try:
            require("gpt-4o")
        except VisionNotSupportedError:
            self.fail("require() raised VisionNotSupportedError for gpt-4o")

    # ── Result dict ───────────────────────────────────────────────────────────

    def test_to_dict_contains_all_fields(self):
        r = check("gpt-4o")
        d = r.to_dict()
        self.assertIn("supported", d)
        self.assertIn("model_id", d)
        self.assertIn("fallback_message", d)
        self.assertIn("suggestion", d)


if __name__ == "__main__":
    unittest.main()