#!/usr/bin/env python3
"""Tests for pin-refresh.py: the local bump, what it leaves alone, and its refusals.

The GitHub half (push, pull request, dispatch, merge) is exercised by running the
workflow; these cover every decision made before anything leaves the checkout.
Standard library only; run with `python3 scripts/pin-refresh-test.py`.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("pin_refresh", HERE / "pin-refresh.py")
assert SPEC and SPEC.loader
pr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr)

CONFIG = """repository = "probityai/demo"
[family]
"pypi:agent-evidence-vectors" = "0.30.0"
[scan]
historical = ["docs/history/**"]
"""
README = """Install with `pip install agent-evidence-vectors==0.30.0`.

The 0.12.0 release added X (pip install agent-evidence-vectors==0.12.0) <!-- version-pins: keep -->
"""
WORKFLOW = "steps:\n  - run: pip install agent-evidence-vectors==0.30.0\n"


def repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="pin-refresh-"))
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True)
    return root


class LocalBump(unittest.TestCase):
    def setUp(self):
        self.root = repo({
            "version-pins.toml": CONFIG,
            "README.md": README,
            "docs/history/0.30.md": "We tested agent-evidence-vectors==0.30.0.\n",
            ".github/workflows/ci.yml": WORKFLOW,
        })
        self.addCleanup(shutil.rmtree, self.root)
        vp = pr.load_version_pins()
        patcher = mock.patch.object(vp, "registry_latest", return_value="0.32.1")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.load = mock.patch.object(pr, "load_version_pins", return_value=vp)
        self.load.start()
        self.addCleanup(self.load.stop)

    def dry_run(self) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = pr.main(["--root", str(self.root), "--config", "version-pins.toml", "--dry-run"])
        return code, out.getvalue()

    def test_moves_the_lock_and_the_live_pin(self):
        code, out = self.dry_run()
        self.assertEqual(code, 0, out)
        self.assertIn('"pypi:agent-evidence-vectors" = "0.32.1"', (self.root / "version-pins.toml").read_text())
        readme = (self.root / "README.md").read_text()
        self.assertIn("agent-evidence-vectors==0.32.1`", readme)
        self.assertIn("version-pins.toml: pypi:agent-evidence-vectors 0.30.0 -> 0.32.1", out)

    def test_history_is_never_moved(self):
        self.dry_run()
        self.assertIn("agent-evidence-vectors==0.12.0", (self.root / "README.md").read_text())
        self.assertIn("==0.30.0", (self.root / "docs/history/0.30.md").read_text())

    def test_workflow_files_are_put_back_for_dependabot(self):
        code, out = self.dry_run()
        self.assertEqual((self.root / ".github/workflows/ci.yml").read_text(), WORKFLOW)
        self.assertIn("left to Dependabot", out)

    def test_nothing_to_do_when_current(self):
        self.dry_run()
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qam", "bumped"], check=True)
        code, out = self.dry_run()
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)

    def test_branch_name_follows_the_change(self):
        self.dry_run()
        first = pr.branch_for(self.root)
        self.assertTrue(first.startswith("pin-refresh/"))
        (self.root / "README.md").write_text("changed\n")
        self.assertNotEqual(first, pr.branch_for(self.root))

    def test_a_registry_that_does_not_answer_is_a_refusal_not_a_pass(self):
        vp = pr.load_version_pins()
        with mock.patch.object(vp, "registry_latest", side_effect=vp.Unread("pypi said 503")):
            err = io.StringIO()
            with mock.patch("sys.stderr", err), redirect_stdout(io.StringIO()):
                code = pr.main(["--root", str(self.root), "--config", "version-pins.toml", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("503", err.getvalue())

    def test_formulas_without_a_tap_refuse(self):
        vp = pr.load_version_pins()
        with mock.patch.object(vp, "formulas", return_value=["probity-verify"]):
            with self.assertRaises(pr.Failed):
                pr.bump(self.root, ["version-pins.toml"], True, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
