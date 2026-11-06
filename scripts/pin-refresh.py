#!/usr/bin/env python3
"""Move a repository's family pins to the newest releases, as a pull request that merges itself when green.

    pin-refresh.py --config version-pins.toml --ci ci.yml            open, test and merge the bump
    pin-refresh.py --config a.toml --config b.toml --ci ci.yml --formulas --tap probityai/tap
    pin-refresh.py --config version-pins.toml --dry-run              show the bump, change nothing remote

WHY THIS EXISTS. Every family release left the other public repositories naming the
release before it: the family locks, the pages they hold and the Homebrew formulas
were moved by hand, days late, and registry-verify went red on a schedule. This runs
in each repository (probityai/.github/actions/pin-refresh) after a family release
and once an hour as the backstop, so a release reaches every page without a person.

WHAT IT DOES, in order. For each config: `version-pins.py refresh` moves the family
lock to the registries and rewrites every page it holds; history is never moved,
because the rewrite reads the same exemptions as the check ([scan] historical,
`version-pins: keep`, `off` ... `on`). With --formulas, each formula's url and sha256
move to its lock and `brew update-python-resources` regenerates its resource blocks.
Files under .github/workflows are put back: the token this runs with may not push
them, and Dependabot owns the Action pins there. If nothing changed it stops. Else it
commits on a branch named after the change, opens a pull request (closing any older
pin-refresh pull request it supersedes), runs each --ci workflow on that branch,
waits, and merges only when every run concluded success. A run that fails leaves the
pull request open with the failing run named, and this exits 1, so the workflow that
called it turns red.

Exit 0 when nothing lags or the bump merged; 1 when a check failed or a pin remains
that nothing here can move; 2 when it could not run (a registry, git or gh failed).
Needs GH_TOKEN with contents, pull-requests and actions write on this repository.

WHY THE PULL REQUEST NEEDS ITS OWN TOKEN. GitHub starts no pull_request run for a push or
a pull request made with the Actions GITHUB_TOKEN, so the required check never appears on
such a pull request: the dispatched CI run passes, and the merge is still refused ("the
base branch policy prohibits the merge"; probityai/.github#31 and probity#256 sat with no
check for hours). With PIN_REFRESH_PR_TOKEN set (a GitHub App or fine-grained token with
contents and pull-requests write), the push, the pull request and the merge use it, its
pull_request run is waited for, and the merge goes through. Without it, a refused merge
exits 1 and names the missing secret instead of reporting that the script could not run.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRANCH_PREFIX = "pin-refresh/"
WORKFLOWS = ".github/workflows/"
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")


def load_version_pins():
    spec = importlib.util.spec_from_file_location("version_pins", HERE / "version-pins.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["version_pins"] = module
    spec.loader.exec_module(module)
    return module


class Failed(Exception):
    """A command this depends on did not succeed; nothing after it may run."""


def run(
    *cmd: str,
    cwd: Path | None = None,
    check: bool = True,
    quiet: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    done = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=False, env=env
    )
    if not quiet:
        print("$ " + " ".join(cmd), flush=True)
    if check and done.returncode != 0:
        raise Failed(f"{' '.join(cmd)} exited {done.returncode}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def pr_token() -> str:
    """The token that opens and merges the pull request: one that starts pull_request runs."""
    return os.environ.get("PIN_REFRESH_PR_TOKEN", "")


def pr_env() -> dict[str, str] | None:
    token = pr_token()
    return {**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token} if token else None


def push_env() -> dict[str, str]:
    """The environment that authenticates a push with GH_TOKEN, kept out of every printed command.

    The checkout's own credential does not survive `brew update-python-resources` in a tap
    (the push failed with "could not read Username"), so the push names the token itself.
    An empty first value clears any header the checkout persisted: a second Authorization
    header makes GitHub refuse the push with HTTP 400 ("Duplicate header"), whichever
    workflow checked the repository out.
    """
    token = pr_token() or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "",
        "GIT_CONFIG_KEY_1": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_1": f"AUTHORIZATION: basic {basic}",
    }


# ---- the local change -------------------------------------------------------------


BREW_DEP = re.compile(r'(?m)^\s*depends_on\s+"([^"]+)"')


def brew_provided(formula: Path) -> list[str]:
    """Python packages the formula takes from brew (depends_on), which must not become resources too."""
    return sorted({d for d in BREW_DEP.findall(formula.read_text(encoding="utf-8")) if not d.startswith("python")})


def update_resources(root: Path, tap: str, name: str) -> None:
    cmd = ["brew", "update-python-resources", "--ignore-non-pypi-packages"]
    provided = brew_provided(root / "Formula" / f"{name}.rb")
    if provided:
        cmd.append("--exclude-packages=" + ",".join(provided))
    run(*cmd, f"{tap}/{name}")


def bump(root: Path, configs: list[str], formulas_on: bool, tap: str | None) -> tuple[list[str], list[str]]:
    """Apply every move this repository can make; return (what moved, pins that remain)."""
    vp = load_version_pins()
    notes: list[str] = []
    remaining: list[str] = []
    for rel in configs:
        cfg = vp.load_config(root, rel)
        before = {e.key: e.version for e in cfg.entries if not e.own}
        vp.refresh(cfg, rel)
        cfg = vp.load_config(root, rel)
        notes += [f"{rel}: {e.key} {before[e.key]} -> {e.version}"
                  for e in cfg.entries if not e.own and before[e.key] != e.version]
        if formulas_on:
            moved = vp.formulas(cfg)
            if moved and not tap:
                raise Failed("--formulas moved a formula and no --tap names it for brew")
            for name in moved:
                update_resources(root, tap, name)
            notes += [f"Formula/{name}.rb: url, sha256 and resources regenerated" for name in moved]
        _, left = vp.write(cfg)
        remaining += [str(f) for f in left]
    return notes, remaining


def restore_workflows(root: Path) -> list[str]:
    changed = [p for p in run("git", "diff", "--name-only", cwd=root, quiet=True).split() if p.startswith(WORKFLOWS)]
    if changed:
        run("git", "checkout", "--", *changed, cwd=root)
    return changed


def branch_for(root: Path) -> str:
    diff = run("git", "diff", "--binary", cwd=root, quiet=True)
    return BRANCH_PREFIX + hashlib.sha256(diff.encode()).hexdigest()[:12]


# ---- GitHub ---------------------------------------------------------------------------


def gh_json(*args: str) -> object:
    return json.loads(run("gh", *args, quiet=True) or "null")


def open_pin_prs(repo: str) -> list[dict]:
    prs = gh_json("pr", "list", "-R", repo, "--state", "open", "--json", "number,headRefName", "--limit", "100")
    return [p for p in prs if p["headRefName"].startswith(BRANCH_PREFIX)]


def dispatch_and_wait(repo: str, workflow: str, branch: str, sha: str, timeout_s: int) -> tuple[str, str]:
    """Run one workflow on the branch; return (conclusion, url) of the run on `sha`."""
    run("gh", "workflow", "run", workflow, "-R", repo, "--ref", branch)
    deadline = time.monotonic() + timeout_s
    run_id = None
    while time.monotonic() < deadline:
        if run_id is None:
            runs = gh_json("run", "list", "-R", repo, "--workflow", workflow, "--branch", branch,
                           "--event", "workflow_dispatch", "--json", "databaseId,headSha", "--limit", "20")
            ids = [r["databaseId"] for r in runs if r["headSha"] == sha]
            run_id = max(ids) if ids else None
        if run_id is not None:
            view = gh_json("run", "view", str(run_id), "-R", repo, "--json", "status,conclusion,url")
            if view["status"] == "completed":
                return view["conclusion"] or "unknown", view["url"]
        time.sleep(20)
    return "timed_out", f"{workflow} on {branch} (run {run_id or 'never started'})"


def wait_pr_checks(repo: str, number: int, sha: str, timeout_s: int) -> tuple[str, str]:
    """Wait for the checks the pull request itself started; return (conclusion, detail)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        view = gh_json("pr", "view", str(number), "-R", repo, "--json", "headRefOid,statusCheckRollup")
        rollup = view["statusCheckRollup"] or []
        if view["headRefOid"] == sha and rollup and all(c.get("status", "COMPLETED") == "COMPLETED" for c in rollup):
            bad = [c.get("name") or c.get("context") for c in rollup
                   if (c.get("conclusion") or c.get("state")) not in ("SUCCESS", "SKIPPED", "NEUTRAL")]
            return ("success", "") if not bad else ("failure", ", ".join(map(str, bad)))
        time.sleep(20)
    return "timed_out", "no completed pull_request checks"


def reuse_pushed_branch(repo: str, root: Path, branch: str, sha: str) -> str:
    """The branch is named after the diff, so one that already exists holds this very bump.

    A new commit of the same tree has another sha (the commit time differs), and pushing it
    over the old one is refused as a non-fast-forward: an hourly run that finds the earlier
    pull request still open failed here, every hour. Stand on the pushed commit instead.
    """
    url = f"https://github.com/{repo}.git"
    if not run("git", "ls-remote", "--heads", url, branch, cwd=root, quiet=True, env=push_env()).strip():
        return sha
    run("git", "fetch", "-q", url, branch, cwd=root, quiet=True, env=push_env())
    if run("git", "diff", "--stat", "FETCH_HEAD", "HEAD", cwd=root, quiet=True).strip():
        return sha
    run("git", "reset", "-q", "--hard", "FETCH_HEAD", cwd=root, quiet=True)
    return run("git", "rev-parse", "HEAD", cwd=root, quiet=True).strip()


def publish(repo: str, root: Path, base: str, notes: list[str], ci: list[str], timeout_s: int) -> int:
    branch = branch_for(root)
    existing = open_pin_prs(repo)
    mine = [p for p in existing if p["headRefName"] == branch]
    run("git", "checkout", "-B", branch, cwd=root)
    run("git", "-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-a", "-s", "-q",
        "-m", "chore(pins): move family pins to the newest releases", "-m", "\n".join(notes), cwd=root)
    sha = run("git", "rev-parse", "HEAD", cwd=root, quiet=True).strip()
    sha = reuse_pushed_branch(repo, root, branch, sha)
    run("git", "push", f"https://github.com/{repo}.git", f"HEAD:refs/heads/{branch}", cwd=root, env=push_env())
    body = ("The family released since these pins were set. This moves each lock, the pages it holds"
            " and any formula, and merges when every check is green.\n\n" + "\n".join(f"- {n}" for n in notes))
    if mine:
        number = mine[0]["number"]
    else:
        url = run("gh", "pr", "create", "-R", repo, "--base", base, "--head", branch,
                  "--title", "chore(pins): move family pins to the newest releases", "--body", body,
                  env=pr_env()).strip()
        number = int(url.rstrip("/").rsplit("/", 1)[1])
    for old in existing:
        if old["headRefName"] != branch:
            run("gh", "pr", "close", str(old["number"]), "-R", repo, "--delete-branch",
                "--comment", f"Superseded by #{number}, which moves the same pins to newer releases.", check=False)
    results = [(wf, *dispatch_and_wait(repo, wf, branch, sha, timeout_s)) for wf in ci]
    for wf, conclusion, url in results:
        print(f"CI {wf}: {conclusion} {url}", flush=True)
    failed = [(wf, c, u) for wf, c, u in results if c != "success"]
    if not failed and pr_token():
        conclusion, detail = wait_pr_checks(repo, number, sha, timeout_s)
        print(f"PR checks: {conclusion} {detail}", flush=True)
        if conclusion != "success":
            failed = [("pull_request checks", conclusion, detail)]
    if failed:
        lines = "\n".join(f"- {wf}: {c} ({u})" for wf, c, u in failed)
        run("gh", "pr", "comment", str(number), "-R", repo, "--body",
            f"Not merged: these checks did not pass on {sha[:12]}.\n\n{lines}", check=False)
        return 1
    try:
        run("gh", "pr", "merge", str(number), "-R", repo, "--squash", "--delete-branch",
            "--match-head-commit", sha, env=pr_env())
    except Failed as exc:
        if pr_token() or "policy prohibits" not in str(exc):
            raise
        print(f"pin-refresh: #{number} passed its dispatched CI but the required check never reached the "
              "pull request: set PIN_REFRESH_PR_TOKEN (pin-refresh input pr-token) to a token that starts "
              "pull_request runs; close and reopen the pull request by hand to run its checks", flush=True)
        return 1
    print(f"MERGED #{number} at {sha}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", action="append", required=True, help="a version-pins.toml, repeatable")
    parser.add_argument("--ci", action="append", default=[], help="a workflow file to run on the bump branch")
    parser.add_argument("--formulas", action="store_true", help="also move Homebrew formulas (needs brew)")
    parser.add_argument("--tap", help="the tap the formulas belong to, for brew (owner/name)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--base", default="main")
    parser.add_argument("--timeout", type=int, default=75 * 60, help="seconds to wait for each CI run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        notes, remaining = bump(root, args.config, args.formulas, args.tap)
        reverted = restore_workflows(root)
        for path in reverted:
            print(f"left to Dependabot (a workflow file this token may not push): {path}")
        for pin in remaining:
            print(f"REMAINS {pin}")
        if remaining:
            print(f"pin-refresh: {len(remaining)} pins remain that no move here fixes; not opening a pull request")
            return 1
        if not run("git", "status", "--porcelain", cwd=root, quiet=True).strip():
            print("pin-refresh: every pin names the newest release; nothing to do")
            return 0
        print("pin-refresh: moved\n" + "\n".join(f"  {n}" for n in notes))
        if args.dry_run:
            print(run("git", "diff", "--stat", cwd=root, quiet=True))
            return 0
        if not args.repo:
            raise Failed("no --repo and no GITHUB_REPOSITORY")
        return publish(args.repo, root, args.base, notes, args.ci, args.timeout)
    except Failed as exc:
        print(f"pin-refresh: could not run: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # a registry, config or decode failure from version-pins
        print(f"pin-refresh: could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
