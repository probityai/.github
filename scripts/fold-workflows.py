#!/usr/bin/env python3
"""Fold every pull-request workflow into one ci.yml with path-selected jobs.

Each workflow under .github/workflows that runs on pull_request becomes a group of
jobs in ci.yml. A `changes` job decides, per group, whether it runs:

- pull_request: the group's own declared paths (and paths-ignore) select it; a change
  under .github/ selects every group, and a group with no path filter always runs;
- schedule: a group runs when it declared that cron;
- push to main: a group runs when it declared a push trigger (its push paths are
  honoured too);
- merge_group and workflow_dispatch: every group runs.

One `ci-ok` job runs with always() and passes only when every job passed or was
skipped by selection; the main ruleset requires it alone. Workflows that do not
run on pull_request (deploys, schedules of their own, manual tasks) stay separate.

Usage:
    fold-workflows.py [--root DIR] [--dry-run]   fold new pull-request workflows into ci.yml
    fold-workflows.py [--root DIR] --check       fail when the repository breaks the one-workflow rule

Folding merges into an existing ci.yml: the groups and jobs already there are kept,
and each newly folded workflow is added beside them, so the tool can be run again
whenever a repository gains a pull-request workflow.

--check enforces the rule folding creates: exactly one workflow under
.github/workflows runs on pull_request, it is triggered on merge_group too, it
supersedes in-flight pull-request runs, and it holds an always() `ci-ok` job that
needs every other job. A second pull-request workflow (a new single-job check) fails
the check and names the file; the repair is to run this tool without --check.
This file is the shared copy: the workflow-fold action in this repository runs it
for every probityai repository, pinned to a commit.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path.cwd()
WF = ROOT / ".github" / "workflows"
OUT = WF / "ci.yml"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"  # v7.0.1
INFRA = [".github/"]

SELECT = r'''import json, os, re, subprocess

def rx(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i): out += "(?:.*/)?"; i += 3
        elif glob.startswith("**", i): out += ".*"; i += 2
        elif glob[i] == "*": out += "[^/]*"; i += 1
        elif glob[i] == "?": out += "[^/]"; i += 1
        else: out += re.escape(glob[i]); i += 1
    return re.compile("^" + out + "$")

def hit(pats, f):
    ok = False
    for p in pats:
        neg = p.startswith("!")
        if rx(p[1:] if neg else p).match(f): ok = not neg
    return ok

def chosen(paths, ignore, files):
    if paths: return any(hit(paths, f) for f in files)
    if ignore: return any(not hit(ignore, f) for f in files)
    return True

groups = json.loads(os.environ["GROUPS"]); infra = tuple(json.loads(os.environ["INFRA"]))
event = os.environ["EVENT"]; run = {}
if event in ("pull_request", "push"):
    base = os.environ["BASE"]
    if event == "push" and (not base or set(base) == {"0"}):
        files = None
    else:
        proc = subprocess.run(["git", "diff", "--name-only", base, os.environ["HEAD"]],
                              capture_output=True, text=True)
        files = proc.stdout.split() if proc.returncode == 0 else None
    wide = files is None or any(f.startswith(infra) for f in files)
    for k, g in groups.items():
        t = g[event]
        if t is None: run[k] = False
        elif wide: run[k] = True
        else: run[k] = chosen(t["paths"], t["ignore"], files)
    print("changed files:", "unknown, selecting all" if files is None else len(files), "wide:", wide)
elif event == "schedule":
    for k, g in groups.items(): run[k] = os.environ["CRON"] in g["crons"]
else:
    for k, g in groups.items(): run[k] = True
print(json.dumps(run, indent=1))
with open(os.environ["GITHUB_OUTPUT"], "a") as fh: fh.write("run=" + json.dumps(run) + "\n")
'''


def as_list(v):
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def trigger(on: dict, event: str):
    if event not in on:
        return None
    spec = on[event] or {}
    return {"paths": as_list(spec.get("paths")), "ignore": as_list(spec.get("paths-ignore"))}


def strip_expr(cond: str) -> str:
    cond = cond.strip()
    m = re.fullmatch(r"\$\{\{(.*)\}\}", cond, re.S)
    return m.group(1).strip() if m else cond


def load(path: pathlib.Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    return doc if isinstance(doc, dict) else {}


def triggers(doc: dict) -> dict:
    on = doc.get(True, doc.get("on"))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {e: None for e in on}
    return on if isinstance(on, dict) else {}


def pull_request_workflows() -> list[pathlib.Path]:
    return [p for p in sorted(WF.glob("*.y*ml")) if "pull_request" in triggers(load(p))]


def check() -> int:
    """The one-workflow rule; every finding is printed, exit 1 on any."""
    found: list[str] = []
    runners = pull_request_workflows()
    owners = [p for p in runners if "ci-ok" in (load(p).get("jobs") or {})]
    if len(owners) != 1:
        found.append(f"{len(owners)} pull-request workflows hold a ci-ok job; exactly one must "
                     f"({', '.join(p.name for p in owners) or 'none'})")
    for p in runners:
        if p not in owners:
            found.append(f"{p.relative_to(ROOT)} runs on pull_request beside the ci-ok workflow; "
                         "fold it in with the shared fold-workflows tool (no --check) and delete it")
    for p in owners:
        doc = load(p)
        jobs = doc.get("jobs") or {}
        ok = jobs["ci-ok"]
        if "merge_group" not in triggers(doc):
            found.append(f"{p.name}: no merge_group trigger, so the merge queue cannot test it")
        if "cancel-in-progress" not in (doc.get("concurrency") or {}):
            found.append(f"{p.name}: no concurrency.cancel-in-progress, so superseded runs keep running")
        if "always()" not in str(ok.get("if", "")):
            found.append(f"{p.name}: ci-ok has no always(), so a skipped or failed job can leave it unreported")
        missing = sorted(set(jobs) - {"ci-ok"} - set(as_list(ok.get("needs"))))
        if missing:
            found.append(f"{p.name}: ci-ok does not need {', '.join(missing)}, so they cannot block a merge")
    for line in found:
        print(f"fold-workflows: {line}", file=sys.stderr)
    print(f"fold-workflows: {len(runners)} pull-request workflow(s), {len(found)} finding(s)")
    return 1 if found else 0


def existing() -> tuple[dict, dict, list[str]]:
    """(groups, jobs, crons) already in ci.yml, so a second fold adds to them."""
    if not OUT.exists():
        return {}, {}, []
    doc = load(OUT)
    jobs = {k: v for k, v in (doc.get("jobs") or {}).items() if k not in ("changes", "ci-ok")}
    select = next(s for s in doc["jobs"]["changes"]["steps"] if s.get("id") == "select")
    groups = json.loads(select["env"]["GROUPS"])
    crons = [c["cron"] for c in triggers(doc).get("schedule") or []]
    return groups, jobs, crons


def main() -> int:
    global ROOT, WF, OUT
    args = sys.argv[1:]
    if "--root" in args:
        ROOT = pathlib.Path(args[args.index("--root") + 1]).resolve()
        WF = ROOT / ".github" / "workflows"
        OUT = WF / "ci.yml"
    if "--check" in args:
        return check()
    dry = "--dry-run" in args
    owner = [p for p in pull_request_workflows() if "ci-ok" in (load(p).get("jobs") or {})]
    if owner and owner[0] != OUT:
        raise SystemExit(f"{owner[0].name} is a hand-written ci-ok workflow; add the new check to it "
                         "as a job (needs: changes if it has one) instead of folding")
    groups, jobs, crons = existing()
    folded: list[pathlib.Path] = []
    kept: list[str] = []
    for path in sorted(WF.glob("*.yml")):
        if path == OUT:
            continue
        doc = yaml.safe_load(path.read_text())
        on = doc.get(True, doc.get("on"))
        if not isinstance(on, dict) or "pull_request" not in on:
            kept.append(path.name)
            continue
        if set(on) - {"pull_request", "push", "schedule", "workflow_dispatch"}:
            kept.append(path.name + " (other triggers)")
            continue
        key = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
        push = trigger(on, "push")
        if push is not None and set(as_list((on["push"] or {}).get("branches"))) - {"main"}:
            raise SystemExit(f"{path.name}: push branches other than main are not folded")
        group_crons = [c["cron"] for c in on.get("schedule") or []]
        crons += [c for c in group_crons if c not in crons]
        groups[key] = {"pull_request": trigger(on, "pull_request"), "push": push,
                       "crons": group_crons}
        wf_perm = doc.get("permissions")
        wf_defaults = doc.get("defaults")
        wf_env = doc.get("env")
        ids = {j: f"{key}__{j}" if len(doc["jobs"]) > 1 else key for j in doc["jobs"]}
        for jid, job in doc["jobs"].items():
            job = dict(job)
            label = job.pop("name", jid)
            new = {"name": f"{doc.get('name', path.stem)} / {label}"}
            needs = [ids[n] for n in as_list(job.pop("needs", None))]
            new["needs"] = ["changes", *needs]
            cond = f"fromJSON(needs.changes.outputs.run).{key}"
            if "if" in job:
                orig = strip_expr(str(job.pop("if")))
                # A status function (always(), failure()) in the original keeps working:
                # the group flag is ANDed with it, so an unselected group still skips.
                cond = f"({orig}) && {cond}"
            elif needs:
                cond = f"{cond} && success()"
            new["if"] = "${{ " + cond + " }}"
            if wf_perm is not None and "permissions" not in job:
                new["permissions"] = wf_perm
            if wf_defaults and "defaults" not in job:
                new["defaults"] = wf_defaults
            if wf_env:
                job["env"] = {**wf_env, **(job.get("env") or {})}
            new.update(job)
            # Expressions that read a sibling job (needs.<id>.result, .outputs) follow
            # the rename.
            raw = json.dumps(new)
            for old_id, new_id in ids.items():
                raw = re.sub(rf"\bneeds\.{re.escape(old_id)}\.", f"needs.{new_id}.", raw)
            jobs[ids[jid]] = json.loads(raw)
        folded.append(path)

    changes = {
        "runs-on": "ubuntu-24.04",
        "timeout-minutes": 5,
        "outputs": {"run": "${{ steps.select.outputs.run }}"},
        "steps": [
            {"uses": CHECKOUT, "with": {"persist-credentials": False, "fetch-depth": 0}},
            {"id": "select", "env": {
                "EVENT": "${{ github.event_name }}",
                "CRON": "${{ github.event.schedule }}",
                "BASE": "${{ github.event.pull_request.base.sha || github.event.before }}",
                "HEAD": "${{ github.event.pull_request.head.sha || github.sha }}",
                "GROUPS": json.dumps(groups, sort_keys=True),
                "INFRA": json.dumps(INFRA)},
             "run": "python3 - <<'PY'\n" + SELECT + "PY\n"},
        ],
    }
    ok = {
        "if": "always()",
        "needs": ["changes", *jobs],
        "runs-on": "ubuntu-24.04",
        "timeout-minutes": 5,
        "steps": [{"name": "Every selected job passed",
                   "env": {"RESULTS": "${{ toJSON(needs) }}"},
                   "run": ("python3 - <<'PY'\nimport json, os\n"
                           "bad = {k: v['result'] for k, v in json.loads(os.environ['RESULTS']).items()\n"
                           "       if v['result'] not in ('success', 'skipped')}\n"
                           "print('jobs that did not pass:', bad or 'none')\n"
                           "raise SystemExit(1 if bad else 0)\nPY\n")}],
    }
    on = {"pull_request": None, "merge_group": None, "push": {"branches": ["main"]}}
    if crons:
        on["schedule"] = [{"cron": c} for c in crons]
    on["workflow_dispatch"] = None
    doc = {
        "name": "ci",
        "on": on,
        "permissions": {"contents": "read"},
        "concurrency": {
            "group": "ci-${{ github.event.pull_request.number || github.ref }}-${{ github.event.schedule || github.event_name }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}"},
        "jobs": {"changes": changes, **jobs, "ci-ok": ok},
    }

    class Dumper(yaml.SafeDumper):
        pass

    def text(dumper, s):
        style = "|" if "\n" in s else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)

    Dumper.add_representer(str, text)
    header = ("# One workflow for every pull-request check. Generated by scripts/fold-workflows.py\n"
              "# from the workflows it replaced; the changes job selects each group by the paths\n"
              "# it declared, its cron, or the event. Branch protection requires only ci-ok.\n")
    body = yaml.dump(doc, Dumper=Dumper, sort_keys=False, width=4096, default_flow_style=False)
    body = body.replace("pull_request: null", "pull_request:").replace(
        "merge_group: null", "merge_group:").replace("workflow_dispatch: null", "workflow_dispatch:")
    print(f"folded {len(folded)} workflows into {len(jobs)} jobs; kept {len(kept)}: {', '.join(kept)}")
    if dry:
        sys.stdout.write(header + body)
        return 0
    OUT.write_text(header + body)
    for p in folded:
        p.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
