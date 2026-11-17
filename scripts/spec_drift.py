#!/usr/bin/env python3
"""Spec drift across the family: names one repository uses that the repository defining them lacks.

    python3 scripts/spec_drift.py --self . --self-repo probityai/probity --family family/

The family's repositories name each other's identifiers in text: a predicate type URI in a
README or a reader, a corpus id in a workflow's ``corpus:`` input or a command line. Each
identifier has one home, the repository that defines it (agent-evidence-vectors defines both
kinds here). When the home drops or renames one, or a consumer names one the home never
published, nothing in either repository fails on its own.

The reusable workflow ``.github/workflows/spec-drift.yml`` checks the calling repository out
at the commit under test and every other family repository at its default branch, then runs
this script. Each check in ``spec-drift.toml`` reads the home's definitions and every family
repository's references. A finding FAILS the run when it sits in the calling repository's
files or when the calling repository is the check's home (the home is where the fix goes);
every other finding is written to the job summary, so a drift is visible from every
repository it touches and fails in the one that must change.

Files are scanned when their suffix is listed in ``scan.suffixes``; paths matching
``scan.skip`` globs (case data, vendored captures) are not, because a corpus case that names
a wrong type URI on purpose is a test, not drift.

Exit 0 when no finding belongs to the calling repository; 1 otherwise; 2 when the
configuration or a checkout is unreadable.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "spec-drift.toml"
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    """One reference whose identifier the home does not define."""

    check: str
    home: str
    repo: str
    path: str
    line: int
    identifier: str

    def text(self) -> str:
        return (
            f"{self.check}: {self.repo}:{self.path}:{self.line} names `{self.identifier}`, "
            f"which {self.home} does not define"
        )


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    """Read and minimally validate ``spec-drift.toml``."""
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("family", "scan", "check"):
        if key not in config:
            raise ValueError(f"{path.name}: missing [{key}]")
    for check in config["check"]:
        if check["id"] not in CHECKS:
            raise ValueError(f"{path.name}: check {check['id']!r} has no implementation")
        if check["home"] not in config["family"]:
            raise ValueError(f"{path.name}: check {check['id']!r} names home {check['home']!r} outside [family]")
    return config


def checkouts(self_dir: Path, self_repo: str, family_dir: Path, family: dict[str, str]) -> dict[str, Path]:
    """Return the checkout of every family repository: the caller's own, the rest by directory name."""
    found = {}
    for repo, directory in family.items():
        path = self_dir if repo == self_repo else family_dir / directory
        if not path.is_dir():
            raise FileNotFoundError(f"no checkout of {repo} at {path}")
        found[repo] = path
    return found


def text_files(root: Path, scan: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield (relative path, text) for every scanned file under ``root``."""
    suffixes = set(scan["suffixes"])
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(relative, pattern) for pattern in scan["skip"]):
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        try:
            yield relative, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def registered_predicates(home: Path) -> set[str]:
    """The predicate names spec/predicates/REGISTRY.md lists, defined or registered."""
    text = (home / "spec" / "predicates" / "REGISTRY.md").read_text(encoding="utf-8")
    return set(re.findall(r"^### `predicate/v1/([a-z0-9-]+)`", text, re.MULTILINE))


def registered_corpora(home: Path) -> set[str]:
    """The corpus ids corpora/REGISTRY.toml publishes."""
    data = tomllib.loads((home / "corpora" / "REGISTRY.toml").read_text(encoding="utf-8"))
    return {str(entry["id"]) for entry in data.get("corpus", [])}


def published_pages(home: Path) -> set[str]:
    """The predicate names the w3id namespace redirects to: pages/predicate/v1/<name>/index.html."""
    root = home / "pages" / "predicate" / "v1"
    return {page.parent.name for page in root.glob("*/index.html")}


PREDICATE_URI = re.compile(r"https://probityai\.github\.io/agent-evidence-vectors/predicate/v1/([a-z0-9-]+)")
W3ID_URI = re.compile(r"https://w3id\.org/agent-evidence/predicate/v1/([a-z0-9-]+)")
CORPUS_USE = re.compile(r"(?:\bcorpus:\s*|--corpus[ =])[\"']?(vectors[a-z0-9-]*)")

CHECKS = {
    "predicate-uri-registered": (registered_predicates, PREDICATE_URI),
    "w3id-predicate-page": (published_pages, W3ID_URI),
    "corpus-id-published": (registered_corpora, CORPUS_USE),
}


def run_check(check: dict[str, Any], trees: dict[str, Path], scan: dict[str, Any]) -> list[Finding]:
    """Return every reference to an identifier the check's home does not define."""
    definitions, pattern = CHECKS[check["id"]]
    defined = definitions(trees[check["home"]])
    findings = []
    for repo, tree in trees.items():
        for relative, text in text_files(tree, scan):
            for number, line in enumerate(text.splitlines(), start=1):
                for match in pattern.finditer(line):
                    if match.group(1) not in defined:
                        findings.append(Finding(check["id"], check["home"], repo, relative, number, match.group(1)))
    return findings


def owned(finding: Finding, self_repo: str) -> bool:
    """Whether a finding fails the caller's run: its file is the caller's, or the caller is the home."""
    return finding.repo == self_repo or finding.home == self_repo


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self", dest="self_dir", type=Path, required=True)
    parser.add_argument("--self-repo", required=True)
    parser.add_argument("--family", type=Path, required=True, help="directory holding the other checkouts")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--summary", type=Path, help="append a Markdown summary here")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.self_repo not in config["family"]:
            raise ValueError(f"{args.self_repo} is not in [family]")
        trees = checkouts(args.self_dir, args.self_repo, args.family, config["family"])
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"spec-drift could not run: {exc}", file=sys.stderr)
        return 2
    findings = [finding for check in config["check"] for finding in run_check(check, trees, config["scan"])]
    mine = [finding for finding in findings if owned(finding, args.self_repo)]
    lines = [f"{len(config['check'])} checks over {len(trees)} repositories: {len(findings)} findings, "
             f"{len(mine)} for {args.self_repo}"]
    lines += [f"FAIL {finding.text()}" for finding in mine]
    lines += [f"elsewhere {finding.text()}" for finding in findings if finding not in mine]
    print("\n".join(lines))
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write("## Spec drift\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    return 1 if mine else 0


if __name__ == "__main__":
    raise SystemExit(main())
