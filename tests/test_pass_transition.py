import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


class PassTransitionTests(unittest.TestCase):
    def test_set_pass_transition_records_target_pass(self):
        spec = importlib.util.spec_from_file_location("ask", SYSTEM / "ask.py")
        ask = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ask)
        rotation = {"current_pass": 2}
        original = ask.write_json
        try:
            ask.write_json = lambda path, data: None
            completed = ask.set_pass_transition(rotation)
        finally:
            ask.write_json = original
        self.assertEqual(completed, 2)
        self.assertTrue(rotation["awaiting_pass_transition"])
        self.assertEqual(rotation["completed_pass"], 2)
        self.assertEqual(rotation["target_pass"], 3)


if __name__ == "__main__":
    unittest.main()
