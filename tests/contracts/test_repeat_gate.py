from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RepeatGateTests(unittest.TestCase):
    def test_gate_rejects_any_run_count_other_than_twenty(self) -> None:
        evidence = ROOT / "artifacts" / "verification" / "M01" / "repeat-gate-invalid-run.json"
        evidence.unlink(missing_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                "tools/contracts/repeat_gate.py",
                "--runs",
                "1",
                "--evidence",
                str(evidence),
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(0)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires exactly 20 runs", completed.stderr)
        self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main()
