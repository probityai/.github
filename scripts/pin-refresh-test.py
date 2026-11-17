#!/usr/bin/env python3
"""Tests for pin-refresh.py: the local bump, what it leaves alone, and its refusals.

The GitHub half (push, pull request, dispatch, merge) is exercised by running the
workflow; these cover every decision made before anything leaves the checkout.
Standard library only; run with `python3 scripts/pin-refresh-test.py`.
"""

from __future__ import annotations

import http.server
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import threading
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


class PushAuth(unittest.TestCase):
    """The push carries exactly one Authorization header, whatever the checkout persisted."""

    def test_a_persisted_checkout_header_is_cleared(self):
        seen: list[list[str]] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get_all("Authorization") or [])
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/"
        root = repo({"a": "a\n"})
        self.addCleanup(shutil.rmtree, root)
        key = f"http.{base}.extraheader"
        subprocess.run(["git", "-C", str(root), "config", key, "AUTHORIZATION: basic b2xk"], check=True)
        with mock.patch.dict("os.environ", {"GH_TOKEN": "new"}):
            env = pr.push_env()
        env["GIT_CONFIG_KEY_0"] = env["GIT_CONFIG_KEY_1"] = key
        subprocess.run(["git", "-C", str(root), "ls-remote", base + "x.git"], env=env,
                       capture_output=True, check=False)
        self.assertEqual(len(seen), 1, seen)
        self.assertEqual(len(seen[0]), 1, f"the request carried {seen[0]}")
        self.assertIn("eC1hY2Nlc3MtdG9rZW46bmV3", seen[0][0])  # x-access-token:new


class PushedBranch(unittest.TestCase):
    """An hourly run that finds its bump already pushed pushes a fast-forward, whatever moved under it."""

    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def setUp(self):
        self.remote = Path(tempfile.mkdtemp(prefix="pin-remote-"))
        self.addCleanup(shutil.rmtree, self.remote)
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self.url = self.remote.as_uri()
        self.root = repo({"version-pins.toml": "a = 1\n", "README.md": "readme\n"})
        self.addCleanup(shutil.rmtree, self.root)
        self.base = self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        self.git(self.root, "push", "-q", self.url, "HEAD:refs/heads/main")

    def bump(self, branch: str) -> str:
        (self.root / "version-pins.toml").write_text("a = 2\n")
        self.git(self.root, "checkout", "-q", "-B", branch)
        self.git(self.root, "commit", "-qam", "bump")
        return self.git(self.root, "rev-parse", "HEAD")

    def push(self, branch: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.root), "push", "-q", self.url, f"HEAD:refs/heads/{branch}"],
                              capture_output=True, text=True, check=False)

    def test_the_same_bump_on_the_same_base_reuses_the_pushed_commit(self):
        first = self.bump("pin-refresh/x")
        self.assertEqual(self.push("pin-refresh/x").returncode, 0)
        self.git(self.root, "checkout", "-q", self.base)
        self.git(self.root, "branch", "-q", "-D", "pin-refresh/x")
        again = self.bump("pin-refresh/x")
        self.assertNotEqual(first, again)
        with redirect_stdout(io.StringIO()):
            got = pr.reuse_pushed_branch(self.url, self.root, "pin-refresh/x", again)
        self.assertEqual(got, first)
        self.assertEqual(self.push("pin-refresh/x").returncode, 0)

    def test_the_same_bump_on_a_moved_base_is_a_fast_forward_with_the_new_tree(self):
        self.bump("pin-refresh/x")
        old_tip = self.git(self.root, "rev-parse", "HEAD")
        self.assertEqual(self.push("pin-refresh/x").returncode, 0)
        self.git(self.root, "checkout", "-q", self.base)
        (self.root / "README.md").write_text("main moved\n")
        self.git(self.root, "commit", "-qam", "main moved")
        self.git(self.root, "push", "-q", self.url, "HEAD:refs/heads/main")
        self.git(self.root, "branch", "-q", "-D", "pin-refresh/x")
        fresh = self.bump("pin-refresh/x")
        tree = self.git(self.root, "rev-parse", "HEAD^{tree}")
        self.assertNotEqual(self.push("pin-refresh/x").returncode, 0, "the plain push must be refused here")
        with redirect_stdout(io.StringIO()):
            got = pr.reuse_pushed_branch(self.url, self.root, "pin-refresh/x", fresh)
        self.assertEqual(self.git(self.root, "rev-parse", f"{got}^{{tree}}"), tree)
        self.assertEqual(self.git(self.root, "rev-parse", f"{got}^1"), old_tip)
        self.assertEqual(self.git(self.root, "rev-parse", f"{got}^2"), fresh)
        self.assertIn("Signed-off-by: github-actions[bot]", self.git(self.root, "log", "-1", "--format=%B", got))
        self.assertEqual(self.push("pin-refresh/x").returncode, 0)

    def test_an_absent_branch_keeps_the_new_commit(self):
        fresh = self.bump("pin-refresh/y")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(pr.reuse_pushed_branch(self.url, self.root, "pin-refresh/y", fresh), fresh)


class BrewResources(unittest.TestCase):
    def test_a_package_brew_provides_is_excluded_from_the_resources(self):
        root = repo({"Formula/demo.rb": 'class Demo < Formula\n  depends_on "cryptography"\n  depends_on "python@3.14"\nend\n'})
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(pr.brew_provided(root / "Formula/demo.rb"), ["cryptography"])
        with mock.patch.object(pr, "run") as run:
            pr.update_resources(root, "probityai/tap", "demo")
        run.assert_called_once_with("brew", "update-python-resources", "--ignore-non-pypi-packages",
                                    "--exclude-packages=cryptography", "probityai/tap/demo")

    def test_no_exclusion_when_brew_provides_no_python_package(self):
        root = repo({"Formula/demo.rb": 'class Demo < Formula\n  depends_on "python@3.14"\nend\n'})
        self.addCleanup(shutil.rmtree, root)
        with mock.patch.object(pr, "run") as run:
            pr.update_resources(root, "probityai/tap", "demo")
        run.assert_called_once_with("brew", "update-python-resources", "--ignore-non-pypi-packages",
                                    "probityai/tap/demo")



class GitHubDecisions(unittest.TestCase):
    """The pure choices of the GitHub half: which run counts and which ref is the merge group."""

    D = "workflow_dispatch"

    def test_an_older_run_on_the_same_commit_never_counts(self):
        runs = [{"databaseId": 10, "headSha": "abc", "event": self.D},
                {"databaseId": 7, "headSha": "abc", "event": self.D}]
        self.assertIsNone(pr.newest_run_after(runs, "abc", baseline=10, event=self.D))

    def test_the_newest_run_after_the_dispatch_counts(self):
        runs = [{"databaseId": 12, "headSha": "abc", "event": self.D},
                {"databaseId": 11, "headSha": "abc", "event": self.D},
                {"databaseId": 13, "headSha": "zzz", "event": self.D},
                {"databaseId": 9, "headSha": "abc", "event": self.D}]
        self.assertEqual(pr.newest_run_after(runs, "abc", baseline=10, event=self.D), 12)

    def test_the_held_pull_request_run_is_not_the_dispatched_run(self):
        # probityai/probity#349: the dispatched run 44107698578 passed; the pull_request run
        # 44107705042 GitHub held for approval was created two seconds later and was read instead.
        runs = [{"databaseId": 44107705042, "headSha": "8363c12c", "event": "pull_request",
                 "status": "completed", "conclusion": "action_required"},
                {"databaseId": 44107698578, "headSha": "8363c12c", "event": self.D,
                 "status": "completed", "conclusion": "success"}]
        self.assertEqual(pr.newest_run_after(runs, "8363c12c", baseline=44107600000, event=self.D), 44107698578)

    def test_a_run_without_its_event_never_counts(self):
        self.assertIsNone(pr.newest_run_after([{"databaseId": 12, "headSha": "abc"}], "abc", 10, self.D))

    def test_the_merge_group_ref_is_found_for_its_pull_request_only(self):
        refs = [
            {"ref": "refs/heads/gh-readonly-queue/main/pr-28-aaaa", "object": {"sha": "s28"}},
            {"ref": "refs/heads/gh-readonly-queue/main/pr-288-bbbb", "object": {"sha": "s288"}},
        ]
        self.assertEqual(pr.queue_ref_for(refs, "main", 288), ("gh-readonly-queue/main/pr-288-bbbb", "s288"))
        self.assertIsNone(pr.queue_ref_for(refs, "main", 2))
        self.assertIsNone(pr.queue_ref_for([], "main", 288))

    def test_a_pull_request_run_held_for_approval_did_not_start(self):
        runs = [{"databaseId": 5, "headSha": "abc", "event": "pull_request", "status": "completed",
                 "conclusion": "action_required"}]
        started, why = pr.pull_request_run(runs, "abc")
        self.assertFalse(started)
        self.assertIn("action_required", why)
        held_status = [{"databaseId": 5, "headSha": "abc", "event": "pull_request", "status": "action_required",
                        "conclusion": None}]
        self.assertFalse(pr.pull_request_run(held_status, "abc")[0])

    def test_a_queued_or_finished_pull_request_run_started(self):
        for status, conclusion in (("queued", None), ("in_progress", None), ("completed", "success"),
                                   ("completed", "failure")):
            runs = [{"databaseId": 6, "headSha": "abc", "event": "pull_request", "status": status,
                     "conclusion": conclusion}]
            self.assertTrue(pr.pull_request_run(runs, "abc")[0], (status, conclusion))

    def test_only_a_pull_request_run_on_the_head_counts(self):
        runs = [{"databaseId": 7, "headSha": "abc", "event": "workflow_dispatch", "status": "completed",
                 "conclusion": "success"},
                {"databaseId": 8, "headSha": "old", "event": "pull_request", "status": "completed",
                 "conclusion": "success"}]
        started, why = pr.pull_request_run(runs, "abc")
        self.assertFalse(started)
        self.assertIn("no pull_request run", why)

    def test_the_newest_pull_request_run_decides(self):
        runs = [{"databaseId": 9, "headSha": "abc", "event": "pull_request", "status": "completed",
                 "conclusion": "success"},
                {"databaseId": 10, "headSha": "abc", "event": "pull_request", "status": "completed",
                 "conclusion": "action_required"}]
        self.assertFalse(pr.pull_request_run(runs, "abc")[0])

    def test_stale_pin_branches_spare_open_pull_requests_and_the_current_one(self):
        refs = [{"ref": f"refs/heads/pin-refresh/{n}"} for n in ("a1", "b2", "c3", "d4")]
        self.assertEqual(pr.stale_pin_branches(refs, {"pin-refresh/b2"}, keep="pin-refresh/d4"),
                         ["pin-refresh/a1", "pin-refresh/c3"])
        self.assertEqual(pr.stale_pin_branches([{"ref": "refs/heads/main"}], set(), keep=""), [])

    def test_no_second_credential_is_read(self):
        source = (HERE / "pin-refresh.py").read_text(encoding="utf-8")
        self.assertNotIn("PIN_REFRESH_PR_TOKEN", source)

class VerifyPr(unittest.TestCase):
    """--verify-pr reads only, and a held run is a refusal, never a pass."""

    def runs_for(self, conclusion):
        return [{"databaseId": 1, "headSha": "h1", "event": "pull_request", "status": "completed",
                 "conclusion": conclusion}]

    def call(self, conclusion):
        def fake(*args, **kwargs):
            if args[:2] == ("pr", "view"):
                return {"headRefName": "pin-refresh/x", "headRefOid": "h1"}
            if args[:2] == ("run", "list"):
                return self.runs_for(conclusion)
            raise AssertionError(f"--verify-pr made a call that is not a read: {args}")
        out = io.StringIO()
        with mock.patch.object(pr, "gh_json", side_effect=fake), redirect_stdout(out):
            code = pr.main(["--config", "version-pins.toml", "--ci", "ci.yml", "--repo", "o/r", "--verify-pr", "7"])
        return code, out.getvalue()

    def test_a_started_run_passes(self):
        code, out = self.call("success")
        self.assertEqual(code, 0, out)

    def test_a_held_run_fails(self):
        code, out = self.call("action_required")
        self.assertEqual(code, 1, out)
        self.assertIn("NOT STARTED ci.yml", out)

    def test_no_ci_workflow_is_a_refusal(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err), redirect_stdout(io.StringIO()):
            code = pr.main(["--config", "version-pins.toml", "--repo", "o/r", "--verify-pr", "7"])
        self.assertEqual(code, 2)


class AppPath(unittest.TestCase):
    """--pr-events: assert the pull request's own run, hand the merge to the repository, never dispatch."""

    def test_a_started_run_turns_on_auto_merge_and_dispatches_nothing(self):
        calls = []
        with mock.patch.object(pr, "await_pull_request_runs", return_value=[]), \
                mock.patch.object(pr, "auto_merge", side_effect=lambda *a: calls.append(a)), \
                mock.patch.object(pr, "run") as run, redirect_stdout(io.StringIO()):
            code = pr.hand_to_repository("o/r", "main", 7, "pin-refresh/x", "h1", ["ci.yml"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("o/r", "main", 7, "h1")])
        self.assertFalse([c for c in run.call_args_list if c.args[:3] == ("gh", "workflow", "run")])

    def test_a_held_run_comments_and_fails(self):
        with mock.patch.object(pr, "await_pull_request_runs", return_value=["ci.yml: held"]), \
                mock.patch.object(pr, "auto_merge") as merge, \
                mock.patch.object(pr, "run") as run, redirect_stdout(io.StringIO()):
            code = pr.hand_to_repository("o/r", "main", 7, "pin-refresh/x", "h1", ["ci.yml"])
        self.assertEqual(code, 1)
        merge.assert_not_called()
        self.assertEqual(run.call_args.args[:3], ("gh", "pr", "comment"))

    def test_auto_merge_is_not_asked_twice(self):
        with mock.patch.object(pr, "gh_json", return_value={"autoMergeRequest": {"enabledAt": "x"}}), \
                mock.patch.object(pr, "run") as run, redirect_stdout(io.StringIO()):
            pr.auto_merge("o/r", "main", 7, "h1")
        run.assert_not_called()

    def test_a_queue_branch_is_asked_without_a_merge_method(self):
        with mock.patch.object(pr, "gh_json", return_value={"autoMergeRequest": None}), \
                mock.patch.object(pr, "pr_queue_state", return_value=("OPEN", False)), \
                mock.patch.object(pr, "has_merge_queue", return_value=True), \
                mock.patch.object(pr, "run") as run:
            pr.auto_merge("o/r", "main", 7, "h1")
        run.assert_called_once_with("gh", "pr", "merge", "7", "-R", "o/r", "--auto", "--match-head-commit", "h1")


class ActionWiring(unittest.TestCase):
    """The composite action mints an App token only when both halves are given, and says which path it took."""

    def setUp(self):
        self.text = (HERE.parent / "actions" / "pin-refresh" / "action.yml").read_text(encoding="utf-8")

    def test_the_app_token_step_is_pinned_and_conditional(self):
        self.assertRegex(self.text, r"actions/create-github-app-token@[0-9a-f]{40} # v\d")
        self.assertIn("inputs.app-client-id != '' && inputs.app-private-key != ''", self.text)

    def test_the_app_path_passes_pr_events(self):
        self.assertIn("--pr-events", self.text)
        self.assertIn("steps.app.outputs.token", self.text)

    def test_half_an_app_is_a_refusal(self):
        self.assertIn("one half of the App", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
