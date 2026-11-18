#!/usr/bin/env python3
"""Move a repository's family pins to the newest releases, as a pull request that merges itself when green.

    pin-refresh.py --config version-pins.toml --ci ci.yml            open, test and merge the bump
    pin-refresh.py --config a.toml --config b.toml --ci ci.yml --formulas --tap probityai/tap
    pin-refresh.py --config version-pins.toml --dry-run              show the bump, change nothing remote
    pin-refresh.py --config version-pins.toml --ci ci.yml --pr-events     GH_TOKEN is an App installation token
    pin-refresh.py --config version-pins.toml --ci ci.yml --verify-pr 349 read only: has #349 a real pull_request run?

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

TWO WAYS TO LAND, CHOSEN BY THE TOKEN.

With --pr-events, GH_TOKEN is a GitHub App installation token (the action mints one when it
is given an App), and what it does starts workflows like a person's push does: the pull
request gets its own pull_request run and the merge queue its merge_group run. So this
opens the pull request, asserts that a pull_request run of each --ci workflow started on its
head (a run GitHub holds as action_required means the token was the Actions token after
all, and is a refusal), turns on auto-merge, and ends. The repository's own branch rules
and merge queue decide the merge; nothing here waits for CI or dispatches it.

Without it, GH_TOKEN is the Actions GITHUB_TOKEN. GitHub then holds the pull request's own
pull_request run as action_required, with no jobs, until a person approves it, and starts
no merge_group run either; it does start a workflow_dispatch run, and a required check is
matched by its name and its app on the commit, whatever event ran it. So every check this
waits for is a workflow_dispatch run it started itself, and only one created after its own
dispatch counts (an older run on the same commit once passed for a new one that failed;
probityai/.github#33). The held pull_request run is created about two seconds after the
dispatch, and counting it as the dispatched run failed every refresh from 14 to 17 Nov 2026
while the dispatched run passed (probityai/probity#338, #349), so the event is part of the
match. Where the base branch has a merge queue, a direct merge is refused ("Cannot use
--delete-branch when merge queue enabled", "the base branch policy prohibits the merge";
probityai/probity#288, probityai/agent-evidence-vectors#530), so the pull request is
enqueued and each --ci workflow is dispatched on the queue's own gh-readonly-queue ref when
no run of it reached that commit. This path stays for a repository with no App: it needs
no secret, at the cost of a job that waits up to two CI runs and a pull request whose own
run never starts.

--verify-pr N changes nothing: it reads pull request N's head and exits 0 only when each
--ci workflow has a pull_request run there that GitHub did not hold for approval.
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


def push_env() -> dict[str, str]:
    """The environment that authenticates a push with GH_TOKEN, kept out of every printed command.

    The checkout's own credential does not survive `brew update-python-resources` in a tap
    (the push failed with "could not read Username"), so the push names the token itself.
    An empty first value clears any header the checkout persisted: a second Authorization
    header makes GitHub refuse the push with HTTP 400 ("Duplicate header"), whichever
    workflow checked the repository out.
    """
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
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


def changed_paths(root: Path) -> list[str]:
    """Every path the working tree changes against HEAD, untracked files included."""
    out = run("git", "status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=root, quiet=True)
    fields = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # a rename or copy names its source in the next field
            i += 1
    return sorted(set(paths))


CARRIED_BRANCH = BRANCH_PREFIX + "carried"


def branch_for(root: Path, moved: list[str]) -> str:
    """Named after the pin move alone, so a file the caller rewrites each run never renames it.

    The calling workflow may change files before this runs (probityai/probity writes its
    download badges). Those ride along, but when the name hashed the whole tree, each new
    download count renamed the branch and closed the pull request before it could land:
    fifteen bump pull requests in ten days, two merged, both by hand (probityai/probity
    #279 to #349). A run that moved no pin and carries only such files uses one fixed branch,
    which the next run moves forward (reuse_pushed_branch).
    """
    if not moved:
        return CARRIED_BRANCH
    diff = run("git", "diff", "--binary", "HEAD", "--", *moved, cwd=root, quiet=True)
    return BRANCH_PREFIX + hashlib.sha256(diff.encode()).hexdigest()[:12]


def describe(notes: list[str], moved: list[str], carried: list[str]) -> tuple[str, str]:
    """(title, body) that say what this pull request changes, and nothing it does not.

    Until 17 Nov 2026 every pull request said "The family released since these pins were set",
    including probityai/probity#349, whose only files were download badges the calling
    workflow wrote.
    """
    lines = [f"- {n}" for n in notes]
    if not notes:
        lines += [f"- {m}: rewritten to the version its lock names" for m in moved]
    lines += [f"- {c}: written by the calling workflow before the refresh ran" for c in carried]
    if notes:
        title = "chore(pins): move family pins to the newest releases"
        lead = ("The family released since these pins were set. This moves each lock, the pages it holds"
                " and any formula, and merges when every check is green.")
    elif moved:
        title = "chore(pins): bring pages to the versions their locks name"
        lead = ("No lock moved; these pages named another version than their lock. This rewrites them and"
                " merges when every check is green.")
    else:
        title = "chore: refresh the files the pin-refresh workflow writes"
        lead = ("No family pin moved. This carries only the files the calling workflow wrote before the"
                " refresh ran, and merges when every check is green.")
    return title, lead + "\n\n" + "\n".join(lines)


# ---- GitHub ---------------------------------------------------------------------------


def gh_json(*args: str) -> object:
    return json.loads(run("gh", *args, quiet=True) or "null")


def open_pin_prs(repo: str) -> list[dict]:
    """Open pull requests from this repository's own pin-refresh branches.

    A fork's branch can carry the same name; that pull request is someone else's, and this
    must never close it as superseded or take its number as its own.
    """
    prs = gh_json("pr", "list", "-R", repo, "--state", "open", "--json", "number,headRefName,isCrossRepository",
                  "--limit", "100")
    return [p for p in prs if p["headRefName"].startswith(BRANCH_PREFIX) and p.get("isCrossRepository") is False]


def newest_run_after(runs: list[dict], sha: str, baseline: int, event: str) -> int | None:
    """The newest `event` run on `sha` created after `baseline`.

    An older run on the same commit never counts, and neither does a run of another event:
    the pull_request run GitHub holds for approval is created after the dispatch and is
    newer than the run this started (the module docstring has the cases).
    """
    ids = [r["databaseId"] for r in runs
           if r["headSha"] == sha and r["databaseId"] > baseline and r.get("event") == event]
    return max(ids) if ids else None


HELD = "action_required"
NEVER_RAN = "startup_failure"
RED = ("failure", "cancelled", "timed_out")


def pull_request_run(runs: list[dict], sha: str) -> tuple[bool, str]:
    """(started, why) for the newest pull_request run on `sha`.

    A run GitHub holds for approval (status or conclusion action_required, no jobs) did not
    start: that is what the Actions token gets for a pull request it opened.
    """
    prs = [r for r in runs if r["headSha"] == sha and r.get("event") == "pull_request"]
    if not prs:
        return False, f"no pull_request run on {sha[:12]}"
    newest = max(prs, key=lambda r: r["databaseId"])
    rid = newest["databaseId"]
    if HELD in (newest.get("status"), newest.get("conclusion")):
        return False, (f"pull_request run {rid} on {sha[:12]} is held as {HELD}: the token that opened the"
                       " pull request starts no workflow (the Actions token); give the action an App")
    if newest.get("conclusion") == NEVER_RAN:
        # The workflow file did not load (a parse or permission error): GitHub made the run and ran no job.
        return False, f"pull_request run {rid} on {sha[:12]} ended as {NEVER_RAN}: the workflow never ran a job"
    return True, f"pull_request run {rid} on {sha[:12]} ({newest.get('status')} {newest.get('conclusion') or ''})".rstrip()


def list_runs(repo: str, workflow: str, branch: str) -> list[dict]:
    return gh_json("run", "list", "-R", repo, "--workflow", workflow, "--branch", branch,
                   "--json", "databaseId,headSha,event,status,conclusion", "--limit", "50") or []


def await_pull_request_runs(repo: str, branch: str, sha: str, ci: list[str], timeout_s: int) -> list[str]:
    """Wait until each --ci workflow has a pull_request run on `sha`; return the ones that did not start."""
    deadline = time.monotonic() + timeout_s
    pending = list(ci)
    reasons: dict[str, str] = {}
    while True:
        for wf in list(pending):
            started, why = pull_request_run(list_runs(repo, wf, branch), sha)
            reasons[wf] = why
            if started:
                print(f"CI {wf}: {why}", flush=True)
                pending.remove(wf)
        held = [wf for wf in pending if HELD in reasons[wf]]
        if not pending or held or time.monotonic() >= deadline:
            return [f"{wf}: {reasons[wf]}" for wf in pending]
        time.sleep(15)


def verify_pr(repo: str, number: int, ci: list[str], timeout_s: int) -> int:
    """The read-only check behind --verify-pr: 0 when every --ci workflow really ran on the head."""
    if not ci:
        raise Failed("--verify-pr needs at least one --ci workflow to look for")
    view = gh_json("pr", "view", str(number), "-R", repo, "--json", "headRefName,headRefOid")
    missing = await_pull_request_runs(repo, view["headRefName"], view["headRefOid"], ci, timeout_s)
    for line in missing:
        print(f"NOT STARTED {line}", flush=True)
    print(f"pin-refresh: #{number} " + ("has a pull_request run of every --ci workflow" if not missing
                                         else f"lacks {len(missing)} of {len(ci)} pull_request runs"), flush=True)
    return 1 if missing else 0


def dispatch_and_wait(repo: str, workflow: str, branch: str, sha: str, timeout_s: int) -> tuple[str, str]:
    """Run one workflow on the branch; return (conclusion, url) of the run it started on `sha`."""
    baseline = max((r["databaseId"] for r in list_runs(repo, workflow, branch)), default=0)
    run("gh", "workflow", "run", workflow, "-R", repo, "--ref", branch)
    return wait_run(repo, workflow, branch, sha, baseline, timeout_s)


def wait_run(repo: str, workflow: str, branch: str, sha: str, baseline: int, timeout_s: int) -> tuple[str, str]:
    deadline = time.monotonic() + timeout_s
    run_id = None
    while time.monotonic() < deadline:
        if run_id is None:
            run_id = newest_run_after(list_runs(repo, workflow, branch), sha, baseline, "workflow_dispatch")
        if run_id is not None:
            view = gh_json("run", "view", str(run_id), "-R", repo, "--json", "status,conclusion,url")
            if view["status"] == "completed":
                return view["conclusion"] or "unknown", view["url"]
        time.sleep(20)
    return "timed_out", f"{workflow} on {branch} (run {run_id or 'never started'})"


def has_merge_queue(repo: str, base: str) -> bool:
    rules = gh_json("api", f"repos/{repo}/rules/branches/{base}") or []
    return any(r.get("type") == "merge_queue" for r in rules)


def queue_ref_for(refs: list[dict], base: str, number: int) -> tuple[str, str] | None:
    """(branch, sha) of the merge group GitHub built for pull request `number`, if any."""
    prefix = f"refs/heads/gh-readonly-queue/{base}/pr-{number}-"
    hits = [(r["ref"].removeprefix("refs/heads/"), r["object"]["sha"]) for r in refs if r["ref"].startswith(prefix)]
    return hits[-1] if hits else None


def enqueue(repo: str, number: int, sha: str) -> None:
    node = gh_json("pr", "view", str(number), "-R", repo, "--json", "id")["id"]
    run("gh", "api", "graphql", "-f",
        "query=mutation($id:ID!,$oid:GitObjectID!){enqueuePullRequest(input:{pullRequestId:$id,"
        "expectedHeadOid:$oid}){mergeQueueEntry{position}}}", "-f", f"id={node}", "-f", f"oid={sha}")


def pr_queue_state(repo: str, number: int) -> tuple[str, bool]:
    owner, name = repo.split("/", 1)
    data = gh_json("api", "graphql", "-f",
                   "query=query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p)"
                   "{state isInMergeQueue}}}", "-f", f"o={owner}", "-f", f"n={name}", "-F", f"p={number}")
    pull = data["data"]["repository"]["pullRequest"]
    return pull["state"], bool(pull["isInMergeQueue"])


def land_through_queue(repo: str, base: str, number: int, sha: str, ci: list[str], timeout_s: int,
                       grace_s: int = 180) -> tuple[bool, str]:
    """Enqueue, make sure every --ci workflow runs on the merge group, and wait for the merge.

    GitHub refusing the enqueue is a refused merge, not a command that could not run: it is
    reported on the pull request like a failed check (probityai/probity run 44196485175 waited
    41 minutes, was refused with "Required status check \"ci-ok\" is expected" and exited 2
    with nothing on #349).
    """
    try:
        enqueue(repo, number, sha)
    except Failed as exc:
        return False, "GitHub refused to queue it: " + re.sub(r"^.*? exited \d+: ", "", str(exc), flags=re.S)
    print(f"QUEUED #{number} at {sha}", flush=True)
    deadline = time.monotonic() + timeout_s
    served: set[str] = set()
    seen_at: dict[str, float] = {}
    while time.monotonic() < deadline:
        state, queued = pr_queue_state(repo, number)
        if state == "MERGED":
            return True, ""
        refs = gh_json("api", f"repos/{repo}/git/matching-refs/heads/gh-readonly-queue/{base}/pr-{number}-") or []
        group = queue_ref_for(refs, base, number)
        if not queued and group is None:
            return False, f"#{number} left the merge queue without merging"
        if group is not None:
            ref, gsha = group
            seen_at.setdefault(gsha, time.monotonic())
            if gsha not in served and time.monotonic() - seen_at[gsha] >= grace_s:
                for wf in ci:
                    if not [r for r in list_runs(repo, wf, ref) if r["headSha"] == gsha]:
                        print(f"no {wf} run reached merge group {gsha[:12]}; dispatching it on {ref}", flush=True)
                        run("gh", "workflow", "run", wf, "-R", repo, "--ref", ref, check=False)
                served.add(gsha)
        time.sleep(20)
    return False, f"#{number} was not merged within {timeout_s}s"


def stale_pin_branches(refs: list[dict], open_heads: set[str], keep: str) -> list[str]:
    """pin-refresh branches no open pull request uses, except `keep` (the one about to be pushed).

    The repositories do not delete a head branch on merge, and an App-opened pull request is
    merged by the queue after this job ends, so each run removes the branches earlier runs left.
    """
    names = [r["ref"].removeprefix("refs/heads/") for r in refs]
    return sorted(n for n in names if n.startswith(BRANCH_PREFIX) and n not in open_heads and n != keep)


def reap_stale_branches(repo: str, root: Path, open_heads: set[str], keep: str) -> None:
    refs = gh_json("api", f"repos/{repo}/git/matching-refs/heads/{BRANCH_PREFIX}") or []
    for name in stale_pin_branches(refs, open_heads, keep):
        run("git", "push", f"https://github.com/{repo}.git", f":refs/heads/{name}", cwd=root, env=push_env(),
            check=False)


def auto_merge(repo: str, base: str, number: int, sha: str) -> None:
    """Hand the merge to the repository: auto-merge, which a merge-queue branch turns into enqueue-when-green.

    An hourly run finds its own pull request again until it lands; asking twice is refused by
    gh, so a pull request already set to merge or already queued is left as it is.
    """
    if (gh_json("pr", "view", str(number), "-R", repo, "--json", "autoMergeRequest") or {}).get("autoMergeRequest"):
        print(f"#{number} already merges when green", flush=True)
        return
    if pr_queue_state(repo, number)[1]:
        print(f"#{number} is already in the merge queue", flush=True)
        return
    if has_merge_queue(repo, base):
        run("gh", "pr", "merge", str(number), "-R", repo, "--auto", "--match-head-commit", sha)
    else:
        run("gh", "pr", "merge", str(number), "-R", repo, "--auto", "--squash", "--match-head-commit", sha)


def reuse_pushed_branch(url: str, root: Path, branch: str, sha: str) -> str:
    """The branch is named after the diff, so one that already exists holds this very bump.

    A new commit of the same tree has another sha (the commit time differs), and pushing it
    over the old one is refused as a non-fast-forward: an hourly run that finds the earlier
    pull request still open failed here, every hour. Stand on the pushed commit instead.

    The name says nothing about the base, though. Once the default branch moves, the same
    bump on the new base has another tree, and pushing it was refused the same way (the
    probityai/probity refresh of 17 Nov 2026, run 44161410339, on #349). Then a commit with
    the new tree is stood on the pushed tip, with both commits as parents: the push is a
    fast-forward, nothing is forced, and the pull request's head is the bump on today's base.
    """
    if not run("git", "ls-remote", "--heads", url, branch, cwd=root, quiet=True, env=push_env()).strip():
        return sha
    run("git", "fetch", "-q", "--depth=1", url, branch, cwd=root, quiet=True, env=push_env())
    pushed = run("git", "rev-parse", "FETCH_HEAD", cwd=root, quiet=True).strip()
    if run("git", "diff", "--stat", pushed, "HEAD", cwd=root, quiet=True).strip():
        tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, quiet=True).strip()
        message = ("chore(pins): move the same bump onto the current base\n\n"
                   f"Signed-off-by: {BOT[0]} <{BOT[1]}>")
        env = {**os.environ, "GIT_AUTHOR_NAME": BOT[0], "GIT_AUTHOR_EMAIL": BOT[1],
               "GIT_COMMITTER_NAME": BOT[0], "GIT_COMMITTER_EMAIL": BOT[1]}
        moved = run("git", "commit-tree", tree, "-p", pushed, "-p", "HEAD", "-m", message,
                    cwd=root, quiet=True, env=env).strip()
        run("git", "reset", "-q", "--hard", moved, cwd=root, quiet=True)
        return moved
    run("git", "reset", "-q", "--hard", pushed, cwd=root, quiet=True)
    return run("git", "rev-parse", "HEAD", cwd=root, quiet=True).strip()


def publish(repo: str, root: Path, base: str, notes: list[str], ci: list[str], timeout_s: int,
            pr_events: bool = False, moved: list[str] | None = None, carried: list[str] | None = None) -> int:
    moved = moved if moved is not None else changed_paths(root)
    carried = carried or []
    branch = branch_for(root, moved)
    title, body = describe(notes, moved, carried)
    existing = open_pin_prs(repo)
    mine = [p for p in existing if p["headRefName"] == branch]
    if pr_events:
        reap_stale_branches(repo, root, {p["headRefName"] for p in existing}, branch)
    run("git", "checkout", "-B", branch, cwd=root)
    run("git", "add", "-A", "--", *moved, *carried, cwd=root)
    run("git", "-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-s", "-q",
        "-m", title, "-m", body.split("\n\n", 1)[1], cwd=root)
    sha = run("git", "rev-parse", "HEAD", cwd=root, quiet=True).strip()
    sha = reuse_pushed_branch(f"https://github.com/{repo}.git", root, branch, sha)
    run("git", "push", f"https://github.com/{repo}.git", f"HEAD:refs/heads/{branch}", cwd=root, env=push_env())
    if mine:
        number = mine[0]["number"]
    else:
        url = run("gh", "pr", "create", "-R", repo, "--base", base, "--head", branch,
                  "--title", title, "--body", body).strip()
        number = int(url.rstrip("/").rsplit("/", 1)[1])
    for old in existing:
        if old["headRefName"] != branch:
            run("gh", "pr", "close", str(old["number"]), "-R", repo, "--delete-branch",
                "--comment", f"Superseded by #{number}, which moves the same pins to newer releases.", check=False)
    if pr_events:
        return hand_to_repository(repo, base, number, branch, sha, ci, root=root)
    results = [(wf, *dispatch_and_wait(repo, wf, branch, sha, timeout_s)) for wf in ci]
    for wf, conclusion, url in results:
        print(f"CI {wf}: {conclusion} {url}", flush=True)
    failed = [(wf, c, u) for wf, c, u in results if c != "success"]
    if failed:
        lines = "\n".join(f"- {wf}: {c} ({u})" for wf, c, u in failed)
        run("gh", "pr", "comment", str(number), "-R", repo, "--body",
            f"Not merged: these checks did not pass on {sha[:12]}.\n\n{lines}", check=False)
        return 1
    if has_merge_queue(repo, base):
        merged, why = land_through_queue(repo, base, number, sha, ci, timeout_s)
        if not merged:
            run("gh", "pr", "comment", str(number), "-R", repo, "--body", f"Not merged: {why}.", check=False)
            print(f"pin-refresh: {why}", flush=True)
            return 1
    else:
        run("gh", "pr", "merge", str(number), "-R", repo, "--squash", "--match-head-commit", sha)
    run("git", "push", f"https://github.com/{repo}.git", f":refs/heads/{branch}", cwd=root, env=push_env(),
        check=False)
    print(f"MERGED #{number} at {sha}", flush=True)
    return 0


def restart_held_head(url: str, root: Path, branch: str, sha: str) -> str:
    """Push one commit of the same tree on `sha`, so the App's push starts the pull request's runs.

    A bump opened while the action ran on the Actions token has a head whose pull_request run
    GitHub holds for approval. When the App takes over and the tree is unchanged, the run
    reuses that very commit, the push changes nothing, no event fires, and the held run is all
    there is: every hourly run refused the same pull request. A new commit pushed with the App
    token is a synchronize event GitHub starts like a person's.
    """
    tree = run("git", "rev-parse", f"{sha}^{{tree}}", cwd=root, quiet=True).strip()
    env = {**os.environ, "GIT_AUTHOR_NAME": BOT[0], "GIT_AUTHOR_EMAIL": BOT[1],
           "GIT_COMMITTER_NAME": BOT[0], "GIT_COMMITTER_EMAIL": BOT[1]}
    message = ("chore(pins): start the checks the Actions token could not\n\n"
               f"Signed-off-by: {BOT[0]} <{BOT[1]}>")
    fresh = run("git", "commit-tree", tree, "-p", sha, "-m", message, cwd=root, quiet=True, env=env).strip()
    run("git", "push", url, f"{fresh}:refs/heads/{branch}", cwd=root, env=push_env())
    return fresh


def hand_to_repository(repo: str, base: str, number: int, branch: str, sha: str, ci: list[str],
                       root: Path | None = None) -> int:
    """The App path: the pull request's own runs started, so auto-merge and the queue finish it."""
    missing = await_pull_request_runs(repo, branch, sha, ci, timeout_s=300)
    if missing and root is not None and all(HELD in m for m in missing):
        print(f"#{number}: the head {sha[:12]} was held under the Actions token; pushing it again with the App",
              flush=True)
        sha = restart_held_head(f"https://github.com/{repo}.git", root, branch, sha)
        missing = await_pull_request_runs(repo, branch, sha, ci, timeout_s=300)
    if missing:
        lines = "\n".join(f"- {m}" for m in missing)
        run("gh", "pr", "comment", str(number), "-R", repo, "--body",
            f"Not merged: the pull request's own checks did not start on {sha[:12]}.\n\n{lines}", check=False)
        print(f"pin-refresh: #{number} has no started pull_request run for {len(missing)} of {len(ci)} workflows",
              flush=True)
        return 1
    red = red_pull_request_runs(repo, branch, sha, ci)
    if red:
        # Auto-merge would wait on a red check for good while every hourly run stayed green.
        for line in red:
            print(f"RED {line}", flush=True)
        print(f"pin-refresh: #{number} is red on {sha[:12]}; not handing it to auto-merge", flush=True)
        return 1
    auto_merge(repo, base, number, sha)
    print(f"AUTO-MERGE #{number} at {sha}: the branch rules and merge queue land it", flush=True)
    return 0


def red_pull_request_runs(repo: str, branch: str, sha: str, ci: list[str]) -> list[str]:
    """Each --ci workflow whose newest pull_request run on `sha` finished red."""
    red = []
    for wf in ci:
        prs = [r for r in list_runs(repo, wf, branch) if r["headSha"] == sha and r.get("event") == "pull_request"]
        newest = max(prs, key=lambda r: r["databaseId"]) if prs else None
        if newest and newest.get("status") == "completed" and newest.get("conclusion") in RED:
            red.append(f"{wf}: pull_request run {newest['databaseId']} on {sha[:12]} {newest['conclusion']}")
    return red


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
    parser.add_argument("--pr-events", action="store_true",
                        help="GH_TOKEN is an App installation token: open, assert the pull_request run, auto-merge")
    parser.add_argument("--verify-pr", type=int, metavar="N",
                        help="read only: exit 0 when pull request N has a started pull_request run of each --ci")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.verify_pr is not None:
            if not args.repo:
                raise Failed("no --repo and no GITHUB_REPOSITORY")
            return verify_pr(args.repo, args.verify_pr, args.ci, timeout_s=0)
        before = set(changed_paths(root))
        notes, remaining = bump(root, args.config, args.formulas, args.tap)
        reverted = restore_workflows(root)
        after = changed_paths(root)
        moved = [p for p in after if p not in before]
        carried = [p for p in after if p in before]
        for path in reverted:
            print(f"left to Dependabot (a workflow file this token may not push): {path}")
        for pin in remaining:
            print(f"REMAINS {pin}")
        if remaining:
            print(f"pin-refresh: {len(remaining)} pins remain that no move here fixes; not opening a pull request")
            return 1
        if not after:
            print("pin-refresh: every pin names the newest release; nothing to do")
            return 0
        print("pin-refresh: moved\n" + "\n".join(f"  {n}" for n in notes or ["no family pin"]))
        for path in carried:
            print(f"carried (written before the refresh ran): {path}")
        if args.dry_run:
            print(run("git", "diff", "--stat", cwd=root, quiet=True))
            return 0
        if not args.repo:
            raise Failed("no --repo and no GITHUB_REPOSITORY")
        return publish(args.repo, root, args.base, notes, args.ci, args.timeout, args.pr_events,
                       moved=moved, carried=carried)
    except Failed as exc:
        print(f"pin-refresh: could not run: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # a registry, config or decode failure from version-pins
        print(f"pin-refresh: could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
