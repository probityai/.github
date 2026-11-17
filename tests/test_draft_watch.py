"""Tests for scripts/draft-watch.py: config validation, coverage, Datatracker reads and the UNREAD rule."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "scripts" / "draft-watch.py"
_spec = importlib.util.spec_from_file_location("draft_watch", TOOL)
assert _spec and _spec.loader
dw = importlib.util.module_from_spec(_spec)
sys.modules["draft_watch"] = dw
_spec.loader.exec_module(dw)


def config(tmp: Path, drafts: list[dict], **extra: object) -> Path:
    p = tmp / "draft-tracking.json"
    p.write_text(json.dumps({"drafts": drafts, **extra}), encoding="utf-8")
    return p


PIN = {"slug": "draft-acme-widget", "known_rev": "02", "why": "the widget corpus reads section 4"}


def datatracker(docs: dict[str, tuple[str, str]], replaces: dict[str, str] | None = None,
                authored: dict[int, list[str]] | None = None, titles: dict[str, str] | None = None):
    """A fake Datatracker: docs maps slug -> (rev, state slug); replaces maps old -> new."""
    replaces = replaces or {}
    states = {"active": 1, "expired": 2, "replaced": 3, "rfc": 4}

    def get(path: str) -> dict:
        if path.startswith("/api/v1/doc/relateddocument/"):
            target = path.split("target__name=")[1].split("&")[0]
            new = replaces.get(target)
            return {"objects": [{"source": f"/api/v1/doc/document/{new}/"}] if new else []}
        if path.startswith("/api/v1/doc/document/?"):
            name = path.split("name=")[1].split("&")[0]
            if name not in docs:
                return {"objects": []}
            rev, st = docs[name]
            return {"objects": [{"rev": rev, "states": [f"/api/v1/doc/state/{states[st]}/"]}]}
        if path.startswith("/api/v1/doc/state/"):
            n = int(path.rstrip("/").rsplit("/", 1)[-1])
            return {"slug": {v: k for k, v in states.items()}[n]}
        if path.startswith("/api/v1/doc/documentauthor/"):
            person = int(path.split("person=")[1].split("&")[0])
            return {"objects": [{"document": f"/api/v1/doc/document/{s}/"} for s in (authored or {}).get(person, [])]}
        if path.startswith("/api/v1/doc/document/"):
            slug = path.rstrip("/").rsplit("/", 1)[-1]
            rev, st = docs[slug]
            return {"title": (titles or {}).get(slug, ""), "states": [f"/api/v1/doc/state/{states[st]}/"]}
        raise AssertionError(path)

    return get


class Config(unittest.TestCase):
    def test_valid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            title, pins = dw.load_config(config(Path(d), [PIN]))
        self.assertEqual(title, dw.DEFAULT_TITLE)
        self.assertEqual(pins[0].slug, "draft-acme-widget")

    def test_refusals(self) -> None:
        bad = [
            [],
            [{**PIN, "slug": "draft-acme-widget-02"}],
            [{**PIN, "slug": "rfc9999"}],
            [{**PIN, "known_rev": 2}],
            [{**PIN, "why": ""}],
            [PIN, PIN],
            [{**PIN, "author_person_id": 7}],
            [{**PIN, "watched_keywords": ["widget"]}],
            [{**PIN, "author_person_id": True, "watched_keywords": ["widget"]}],
        ]
        with tempfile.TemporaryDirectory() as d:
            for drafts in bad:
                with self.subTest(drafts=drafts), self.assertRaises(dw.ConfigError):
                    dw.load_config(config(Path(d), drafts))
            with self.assertRaises(dw.ConfigError):
                dw.load_config(Path(d) / "absent.json")

    def test_invalid_config_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            self.assertEqual(dw.main(["check", "--config", str(config(Path(d), []))]), 2)


class Coverage(unittest.TestCase):
    def test_named_drafts(self) -> None:
        text = (
            "see draft-acme-widget-02 and https://www.ietf.org/archive/id/draft-x-y-time-anchor-08.txt; "
            "draft-ietf-oauth-v2-1 has no revision, draft-a-b-25-tail-03 keeps its digits, "
            "draft-gone-thing is named bare, and draft-bu-00 is a shorthand"
        )
        self.assertEqual(
            dw.named_drafts(text),
            {"draft-acme-widget", "draft-x-y-time-anchor", "draft-a-b-25-tail"},
        )

    def test_check_finds_an_unpinned_draft(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = config(Path(d), [PIN])
            f = Path(d) / "matrix.json"
            f.write_text('{"r": "draft-acme-widget-02", "s": "draft-other-thing-00"}', encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                rc = dw.main(["check", "--config", str(cfg), "--require-pinned", str(f)])
            self.assertEqual(rc, 1)
            self.assertIn("draft-other-thing", out.getvalue())
            f.write_text('{"r": "draft-acme-widget-02"}', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(dw.main(["check", "--config", str(cfg), "--require-pinned", str(f)]), 0)

    def test_unwatched_digest_covers_without_naming(self) -> None:
        import hashlib

        digest = hashlib.sha256(b"draft-other-thing").hexdigest()
        with tempfile.TemporaryDirectory() as d:
            cfg = config(Path(d), [PIN], unwatched_sha256=[digest], unwatched_why="not followed here")
            self.assertNotIn("draft-other-thing", cfg.read_text(encoding="utf-8"))
            f = Path(d) / "m.json"
            f.write_text('"draft-acme-widget-02 draft-other-thing-00"', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(dw.main(["check", "--config", str(cfg), "--require-pinned", str(f)]), 0)
            for bad in ({"unwatched_sha256": [digest]}, {"unwatched_sha256": ["XYZ"], "unwatched_why": "w"},
                        {"unwatched_sha256": [hashlib.sha256(b"draft-acme-widget").hexdigest()], "unwatched_why": "w"}):
                with self.subTest(bad=bad), self.assertRaises(dw.ConfigError):
                    dw.load_config(config(Path(d), [PIN], **bad))

    def test_check_refuses_a_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            cfg = config(Path(d), [PIN])
            self.assertEqual(dw.main(["check", "--config", str(cfg), "--require-pinned", f"{d}/nope"]), 2)


class Reads(unittest.TestCase):
    def pin(self, **kw: object) -> object:
        return dw.Pin(**{"slug": "draft-acme-widget", "known_rev": "02", "why": "x", **kw})

    def test_current(self) -> None:
        r = dw.read(datatracker({"draft-acme-widget": ("02", "active")}), self.pin())
        self.assertEqual((r.slug, r.rev, r.state, r.unread, r.notes()), ("draft-acme-widget", "02", "active", "", []))

    def test_new_revision_and_rename(self) -> None:
        get = datatracker(
            {"draft-acme-widget": ("02", "replaced"), "draft-ietf-wg-widget": ("00", "active")},
            replaces={"draft-acme-widget": "draft-ietf-wg-widget"},
        )
        r = dw.read(get, self.pin())
        self.assertEqual(r.slug, "draft-ietf-wg-widget")
        self.assertEqual(len(r.notes()), 2)

    def test_expired(self) -> None:
        r = dw.read(datatracker({"draft-acme-widget": ("02", "expired")}), self.pin())
        self.assertEqual(r.notes(), ["`draft-acme-widget` is now `expired`"])

    def test_keyword_sweep(self) -> None:
        get = datatracker(
            {"draft-acme-widget": ("02", "active"), "draft-acme-widget-ng": ("00", "active"),
             "draft-acme-unrelated": ("00", "active")},
            authored={7: ["draft-acme-widget", "draft-acme-widget-ng", "draft-acme-unrelated"]},
            titles={"draft-acme-widget-ng": "Widget discovery, next", "draft-acme-unrelated": "Gadgets"},
        )
        r = dw.read(get, self.pin(author_person_id=7, watched_keywords=("widget",)))
        self.assertEqual([s for s, _ in r.related], ["draft-acme-widget-ng"])

    def test_failed_read_is_unread_never_quiet(self) -> None:
        def down(path: str) -> dict:
            raise urllib.error.URLError("unreachable")

        r = dw.read(down, self.pin())
        self.assertTrue(r.unread)
        self.assertEqual(r.notes(), [])

    def test_unknown_document_is_unread(self) -> None:
        r = dw.read(datatracker({}), self.pin())
        self.assertIn("no document", r.unread)

    def test_watch_with_an_unread_pin_leaves_the_issue_alone(self) -> None:
        def down(path: str) -> dict:
            raise urllib.error.URLError("unreachable")

        touched: list[object] = []
        real = dw.manage_issue
        dw.manage_issue = lambda *a: touched.append(a) or "touched"
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = dw.cmd_watch("t", [self.pin()], True, "o/r", get=down)
        finally:
            dw.manage_issue = real
        self.assertEqual(rc, 0)
        self.assertEqual(touched, [])
        self.assertIn("0 of 1 read", out.getvalue())

    def test_signature_moves_with_state(self) -> None:
        a = dw.read(datatracker({"draft-acme-widget": ("02", "active")}), self.pin())
        b = dw.read(datatracker({"draft-acme-widget": ("03", "active")}), self.pin())
        self.assertNotEqual(dw.signature([a]), dw.signature([b]))
        self.assertIn(dw.signature([b]), dw.render([b]))


if __name__ == "__main__":
    unittest.main()
