"""Tests for scripts/fold-workflows.py: the one-workflow rule and folding into ci.yml."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

TOOL = Path(__file__).resolve().parents[1] / "scripts" / "fold-workflows.py"

SINGLE = """name: {name}
on:
  pull_request:
    paths: ["{path}/**"]
jobs:
  run:
    runs-on: ubuntu-24.04
    steps:
      - run: echo {name}
"""

HAND_WRITTEN = """name: gate
on:
  pull_request:
  merge_group:
concurrency:
  group: gate-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - run: echo build
  ci-ok:
    if: always()
    needs: [build]
    runs-on: ubuntu-24.04
    steps:
      - run: echo ok
"""


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--root", str(root), *args],
                          capture_output=True, text=True, check=False)


class Repo:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.wf = self.root / ".github" / "workflows"
        self.wf.mkdir(parents=True)

    def add(self, name: str, text: str) -> None:
        (self.wf / name).write_text(text)

    def groups(self) -> list[str]:
        doc = yaml.safe_load((self.wf / "ci.yml").read_text())
        select = next(s for s in doc["jobs"]["changes"]["steps"] if s.get("id") == "select")
        return sorted(json.loads(select["env"]["GROUPS"]))


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.tmp.cleanup)

    def test_a_consolidated_repository_passes(self) -> None:
        self.repo.add("gate.yml", HAND_WRITTEN)
        result = run(self.repo.root, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_second_pull_request_workflow_fails_and_is_named(self) -> None:
        self.repo.add("gate.yml", HAND_WRITTEN)
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        result = run(self.repo.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("lint.yml", result.stderr)

    def test_a_repository_with_no_ci_ok_fails(self) -> None:
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        result = run(self.repo.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("0 pull-request workflows hold a ci-ok job", result.stderr)

    def test_ci_ok_without_always_fails(self) -> None:
        self.repo.add("gate.yml", HAND_WRITTEN.replace("if: always()", "if: success()"))
        result = run(self.repo.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no always()", result.stderr)

    def test_a_job_ci_ok_does_not_need_fails(self) -> None:
        extra = HAND_WRITTEN.replace("jobs:\n", "jobs:\n  lint:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo lint\n", 1)
        self.repo.add("gate.yml", extra)
        result = run(self.repo.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not need lint", result.stderr)

    def test_missing_merge_group_and_cancel_fail(self) -> None:
        text = HAND_WRITTEN.replace("  merge_group:\n", "").replace("  cancel-in-progress: true\n", "")
        self.repo.add("gate.yml", text)
        result = run(self.repo.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no merge_group trigger", result.stderr)
        self.assertIn("cancel-in-progress", result.stderr)

    def test_a_workflow_that_only_runs_on_other_events_is_ignored(self) -> None:
        self.repo.add("gate.yml", HAND_WRITTEN)
        self.repo.add("deploy.yml", "name: deploy\non:\n  push:\n    branches: [main]\njobs:\n  d:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo d\n")
        self.assertEqual(run(self.repo.root, "--check").returncode, 0)


class FoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.tmp.cleanup)

    def test_folding_builds_a_workflow_that_passes_the_check(self) -> None:
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        result = run(self.repo.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo.wf / "lint.yml").exists())
        self.assertEqual(self.repo.groups(), ["lint"])
        self.assertEqual(run(self.repo.root, "--check").returncode, 0)

    def test_a_second_fold_keeps_the_first_groups(self) -> None:
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        run(self.repo.root)
        self.repo.add("docs.yml", SINGLE.format(name="docs", path="docs"))
        result = run(self.repo.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.repo.groups(), ["docs", "lint"])
        doc = yaml.safe_load((self.repo.wf / "ci.yml").read_text())
        self.assertEqual(sorted(doc["jobs"]), ["changes", "ci-ok", "docs", "lint"])
        self.assertEqual(sorted(doc["jobs"]["ci-ok"]["needs"]), ["changes", "docs", "lint"])
        self.assertEqual(run(self.repo.root, "--check").returncode, 0)

    def test_folding_again_with_nothing_new_changes_nothing(self) -> None:
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        run(self.repo.root)
        before = (self.repo.wf / "ci.yml").read_text()
        self.assertEqual(run(self.repo.root).returncode, 0)
        self.assertEqual((self.repo.wf / "ci.yml").read_text(), before)

    def test_folding_refuses_beside_a_hand_written_ci_ok_workflow(self) -> None:
        self.repo.add("gate.yml", HAND_WRITTEN)
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        result = run(self.repo.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hand-written ci-ok workflow", result.stderr)
        self.assertTrue((self.repo.wf / "lint.yml").exists())

    def test_dry_run_writes_nothing(self) -> None:
        self.repo.add("lint.yml", SINGLE.format(name="lint", path="src"))
        result = run(self.repo.root, "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.repo.wf / "lint.yml").exists())
        self.assertFalse((self.repo.wf / "ci.yml").exists())


if __name__ == "__main__":
    unittest.main()
