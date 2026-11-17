#!/usr/bin/env python3
# Copyright 2024-2026 The DNS-AID Authors
# Copyright 2026 The probityai authors
# SPDX-License-Identifier: Apache-2.0
"""Watch every IETF Internet-Draft a repository pins, and keep one tracking issue current.

Adapted from scripts/check_draft_status.py of dns-aid/dns-aid-core at commit
825ccea1259267898df59b80e063317ec6900224 (Apache-2.0). Changes from that version:
one config holds any number of pinned drafts; a draft whose Datatracker read fails is
reported UNREAD and the run then leaves the issue alone, instead of crashing or being
read as quiet; the issue is found by listing the repository's issues, not through the
search index, which lags a just-created issue and opened duplicates; and a `check`
mode, offline, fails when a file the repository names drafts in names one no pin covers.

    draft-watch.py check [--config C] [--require-pinned FILE ...]   offline; exit 1 on a finding
    draft-watch.py watch [--config C] [--manage-issue] [--repo O/R]  network; exit 0 unless the config is invalid

The config, .github/draft-tracking.json by default:

    {
      "issue_title": "[draft-watch] Internet-Draft state",
      "drafts": [
        {"slug": "draft-example-thing", "known_rev": "03", "why": "what in this repository reads it",
         "author_person_id": 12345, "watched_keywords": ["thing"]}
      ]
    }

`author_person_id` and `watched_keywords` are optional and go together: they sweep that
author's other active drafts for a successor filed without a `replaces` relation.
Bump `known_rev` (and `slug` on a rename) in the pull request that brings the repository
in line with the new revision; until then the issue stays open and says what moved.
Exit status: 0 done, 1 a `check` finding, 2 the config is missing or invalid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

DATATRACKER = "https://datatracker.ietf.org"
DEFAULT_CONFIG = Path(".github/draft-tracking.json")
DEFAULT_TITLE = "[draft-watch] Internet-Draft state"
MARKER = re.compile(r"<!-- draft-watch:signature=([0-9a-f]+) -->")
SLUG = re.compile(r"^draft-[a-z0-9]+(?:-[a-z0-9]+)+$")
REV = re.compile(r"^\d{2}$")
# A draft named with its revision, as files cite them: draft-<words>-NN, not followed by more name.
NAMED = re.compile(r"\b(draft-[a-z0-9]+(?:-[a-z0-9]+)*?)-(\d{2})(?![a-z0-9-]*[a-z])")
STATE_PRIORITY = ("rfc", "replaced", "withdrawn", "expired", "active")
ENDED = {"rfc", "replaced", "expired", "withdrawn"}


class ConfigError(Exception):
    """The tracking config is missing or does not hold a valid pin list."""


@dataclass(frozen=True)
class Pin:
    slug: str
    known_rev: str
    why: str
    author_person_id: int | None = None
    watched_keywords: tuple[str, ...] = ()


@dataclass
class Reading:
    pin: Pin
    slug: str = ""
    rev: str = ""
    state: str = ""
    unread: str = ""
    related: list[tuple[str, str]] = field(default_factory=list)

    def notes(self) -> list[str]:
        if self.unread:
            return []
        out = []
        if self.slug != self.pin.slug:
            out.append(f"`{self.pin.slug}` was replaced by `{self.slug}`")
        if self.rev != self.pin.known_rev:
            out.append(f"`{self.slug}` is at revision `{self.rev}` (pinned `{self.pin.known_rev}`)")
        if self.state in ENDED:
            out.append(f"`{self.slug}` is now `{self.state}`")
        out += [f"`{s}` ({t}) may succeed `{self.pin.slug}`" for s, t in self.related]
        return out


def load_config(path: Path) -> tuple[str, list[Pin]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("drafts"), list) or not data["drafts"]:
        raise ConfigError(f"{path}: needs a non-empty `drafts` list")
    title = data.get("issue_title", DEFAULT_TITLE)
    if not isinstance(title, str) or not title.strip():
        raise ConfigError(f"{path}: `issue_title` must be a non-empty string")
    pins: list[Pin] = []
    seen: set[str] = set()
    for i, d in enumerate(data["drafts"]):
        where = f"{path}: drafts[{i}]"
        if not isinstance(d, dict):
            raise ConfigError(f"{where} is not an object")
        slug, rev, why = d.get("slug"), d.get("known_rev"), d.get("why")
        if not isinstance(slug, str) or not SLUG.match(slug) or re.search(r"-\d{2}$", slug):
            raise ConfigError(f"{where}: `slug` must be a draft name without its revision, got {slug!r}")
        if not isinstance(rev, str) or not REV.match(rev):
            raise ConfigError(f"{where}: `known_rev` must be two digits as a string, got {rev!r}")
        if not isinstance(why, str) or not why.strip():
            raise ConfigError(f"{where}: `why` must say what in this repository reads {slug}")
        if slug in seen:
            raise ConfigError(f"{where}: {slug} is pinned twice")
        seen.add(slug)
        author = d.get("author_person_id")
        words = d.get("watched_keywords", [])
        if (author is None) != (not words):
            raise ConfigError(f"{where}: `author_person_id` and `watched_keywords` go together")
        if author is not None and (not isinstance(author, int) or isinstance(author, bool)):
            raise ConfigError(f"{where}: `author_person_id` must be an integer")
        if not isinstance(words, list) or not all(isinstance(w, str) and w for w in words):
            raise ConfigError(f"{where}: `watched_keywords` must be a list of strings")
        pins.append(Pin(slug, rev, why, author, tuple(w.lower() for w in words)))
    return title, pins


def named_drafts(text: str) -> set[str]:
    """Every draft name (without its revision) that the text cites with a revision."""
    return {m.group(1) for m in NAMED.finditer(text)}


def uncovered(pins: list[Pin], files: list[Path]) -> list[str]:
    pinned = {p.slug for p in pins}
    out = []
    for f in files:
        for slug in sorted(named_drafts(f.read_text(encoding="utf-8")) - pinned):
            out.append(f"{f}: names {slug} and no pin in the config covers it")
    return out


# Datatracker reads. `get` is injectable so the tests run offline.
Getter = Callable[[str], dict[str, Any]]


def http_get(path: str) -> dict[str, Any]:
    url = path if path.startswith("http") else DATATRACKER + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - public read-only API
        return json.loads(resp.read().decode("utf-8"))


def _tail(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def resolve(get: Getter, slug: str, hops: int = 10) -> str:
    """Follow `replaces` forward to the draft nothing has replaced yet."""
    seen = {slug}
    for _ in range(hops):
        q = urllib.parse.urlencode({"target__name": slug, "relationship__slug": "replaces", "format": "json"})
        objs = get(f"/api/v1/doc/relateddocument/?{q}").get("objects", [])
        if not objs:
            return slug
        nxt = _tail(objs[0]["source"])
        if nxt in seen:
            return slug
        seen.add(nxt)
        slug = nxt
    return slug


def state_of(get: Getter, uris: list[str]) -> str:
    found = {str(get(u).get("slug") or "").lower() for u in uris}
    for s in STATE_PRIORITY:
        if s in found:
            return s
    return sorted(found - {""})[0] if found - {""} else "unknown"


def sweep(get: Getter, pin: Pin, current: str) -> list[tuple[str, str]]:
    if pin.author_person_id is None:
        return []
    q = urllib.parse.urlencode(
        {"person": pin.author_person_id, "document__type": "draft", "format": "json", "limit": 100}
    )
    out = []
    for entry in get(f"/api/v1/doc/documentauthor/?{q}").get("objects", []):
        slug = _tail(entry["document"])
        if slug in (current, pin.slug):
            continue
        doc = get(entry["document"])
        title = str(doc.get("title") or "")
        if state_of(get, doc.get("states") or []) == "active" and any(
            w in title.lower() for w in pin.watched_keywords
        ):
            out.append((slug, title))
    return out


def read(get: Getter, pin: Pin) -> Reading:
    r = Reading(pin)
    try:
        r.slug = resolve(get, pin.slug)
        q = urllib.parse.urlencode({"name": r.slug, "format": "json"})
        objs = get(f"/api/v1/doc/document/?{q}").get("objects", [])
        if not objs:
            r.unread = f"Datatracker has no document named {r.slug}"
            return r
        r.rev = str(objs[0].get("rev") or "")
        r.state = state_of(get, objs[0].get("states") or [])
        r.related = sweep(get, pin, r.slug)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        r.unread = f"{type(exc).__name__}: {exc}"
    return r


def signature(readings: list[Reading]) -> str:
    raw = "\n".join(
        f"{r.pin.slug}|{r.pin.known_rev}|{r.slug}|{r.rev}|{r.state}|{','.join(s for s, _ in r.related)}"
        for r in sorted(readings, key=lambda r: r.pin.slug)
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def render(readings: list[Reading]) -> str:
    lines = [
        f"<!-- draft-watch:signature={signature(readings)} -->",
        "",
        "Each Internet-Draft this repository pins in `.github/draft-tracking.json`, against the",
        "IETF Datatracker. Bump a pin in the pull request that brings the repository in line with",
        "the new revision; the issue updates on the next run.",
        "",
        "| Pinned | Current | Revision | State | Moved |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in sorted(readings, key=lambda r: r.pin.slug):
        moved = "; ".join(r.notes()) or "no"
        lines.append(
            f"| `{r.pin.slug}-{r.pin.known_rev}` | [`{r.slug}`]({DATATRACKER}/doc/{r.slug}/) "
            f"| `{r.rev}` | `{r.state}` | {moved} |"
        )
    return "\n".join(lines) + "\n"


def gh(args: list[str]) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)  # noqa: S603,S607
    if done.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def find_issue(repo: str, title: str) -> dict[str, Any] | None:
    """The newest issue with exactly this title, read by listing issues, never by search."""
    out = gh(["api", "--paginate", f"repos/{repo}/issues?state=all&per_page=100",
              "--jq", f'.[] | select(.pull_request == null and .title == {json.dumps(title)}) '
              '| {number, state, body}'])
    found = [json.loads(line) for line in out.splitlines() if line.strip()]
    return max(found, key=lambda i: i["number"]) if found else None


def manage_issue(repo: str, title: str, readings: list[Reading]) -> str:
    body = render(readings)
    sig = signature(readings)
    notes = [n for r in readings for n in r.notes()]
    issue = find_issue(repo, title)
    if issue is None:
        if not notes:
            return "no issue and every pin is current: nothing to open"
        url = gh(["issue", "create", "-R", repo, "--title", title, "--body", body]).strip()
        return f"opened {url}"
    old = MARKER.search(issue.get("body") or "")
    if old and old.group(1) == sig:
        return f"issue #{issue['number']} already shows this state"
    number, is_open = str(issue["number"]), str(issue.get("state", "")).lower() == "open"
    gh(["issue", "edit", number, "-R", repo, "--body", body])
    if notes:
        if not is_open:
            gh(["issue", "reopen", number, "-R", repo])
        gh(["issue", "comment", number, "-R", repo, "--body",
            "State changed:\n\n" + "\n".join(f"- {n}" for n in notes)])
    elif is_open:
        gh(["issue", "comment", number, "-R", repo, "--body", "Every pin now matches the Datatracker."])
        gh(["issue", "close", number, "-R", repo])
    return f"updated issue #{number}"


def cmd_check(pins: list[Pin], files: list[Path]) -> int:
    findings = uncovered(pins, files)
    for f in findings:
        print(f"::error::{f}")
    print(f"draft-watch check: {len(pins)} pins; {len(files)} files scanned; {len(findings)} uncovered")
    return 1 if findings else 0


def cmd_watch(title: str, pins: list[Pin], manage: bool, repo: str | None, get: Getter = http_get) -> int:
    readings = [read(get, p) for p in pins]
    for r in readings:
        if r.unread:
            print(f"::warning::{r.pin.slug}: UNREAD ({r.unread})")
        else:
            print(f"{r.pin.slug}-{r.pin.known_rev}: {r.slug}-{r.rev} {r.state}: " + ("; ".join(r.notes()) or "current"))
    unread = [r for r in readings if r.unread]
    moved = [r for r in readings if r.notes()]
    print(f"draft-watch: {len(readings) - len(unread)} of {len(readings)} read; {len(moved)} moved")
    if not manage:
        return 0
    if unread:
        print(f"::warning::{len(unread)} pins unread, so the tracking issue is left as it is this run")
        return 0
    if not repo:
        print("::warning::no repository named (--repo or GITHUB_REPOSITORY); the issue was not touched")
        return 0
    try:
        print(f"draft-watch: {manage_issue(repo, title, readings)}")
    except RuntimeError as exc:
        # A fork's read-only token refuses issue writes; the run reports it and stays informational.
        print(f"::warning::the tracking issue could not be updated: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["check", "watch"])
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--require-pinned", type=Path, nargs="*", default=[])
    ap.add_argument("--manage-issue", action="store_true")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    a = ap.parse_args(argv)
    try:
        title, pins = load_config(a.config)
    except ConfigError as exc:
        print(f"::error::{exc}")
        return 2
    if a.command == "check":
        missing = [f for f in a.require_pinned if not f.is_file()]
        if missing:
            print(f"::error::--require-pinned names files that do not exist: {', '.join(map(str, missing))}")
            return 2
        return cmd_check(pins, a.require_pinned)
    return cmd_watch(title, pins, a.manage_issue, a.repo)


if __name__ == "__main__":
    sys.exit(main())
