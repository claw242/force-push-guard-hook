import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("block_force_push.py")


def run(command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([sys.executable, "-I", str(HOOK)], input=payload,
                          capture_output=True, text=True, timeout=20)


class ForcePushGuardTest(unittest.TestCase):
    def test_blocks_forced_forms(self):
        for command in ("git push --force origin main", "git push -f", "git push origin +main"):
            with self.subTest(command=command):
                self.assertEqual(run(command).returncode, 2)

    def test_plain_push_passes(self):
        self.assertEqual(run("git push origin feature").returncode, 0)

    def test_leading_redirections_are_refused(self):
        for command in ("> /dev/null git push --force origin main",
                        "2>/dev/null git push --force origin main",
                        "env 2>/dev/null git push --force origin main",
                        "git >/dev/null push --force origin main",
                        "git 2>/dev/null push --force origin main"):
            with self.subTest(command=command):
                self.assertEqual(run(command).returncode, 2)

    def test_abbreviated_dangerous_flags_are_refused(self):
        for command in ("git push --force-with-leas origin main",
                        "git push --mirro origin", "git push --del origin main"):
            with self.subTest(command=command):
                self.assertEqual(run(command).returncode, 2)

    def test_malformed_input_refused(self):
        result = subprocess.run([sys.executable, "-I", str(HOOK)], input="not json",
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
