import json
import subprocess
import sys
import unittest
from pathlib import Path


class BootstrapTests(unittest.TestCase):
    def test_dry_run_is_side_effect_free_and_structured(self) -> None:
        script = Path("scripts/bootstrap.py").resolve()
        result = subprocess.run(
            [sys.executable, str(script), "--dry-run"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "dry_run")
        self.assertTrue(payload["executable"].endswith(
            "memnetai-integration.exe" if sys.platform == "win32" else "memnetai-integration"
        ))
        self.assertNotIn("api_key", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
