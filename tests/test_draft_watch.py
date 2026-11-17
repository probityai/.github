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


# The Datatracker's state ids, slugs and types as served on 2026-11-17
# (fixtures/draft-watch/datatracker-states.json): six of type `draft`, and the stream types
# that reuse the slug `active` (56 is draft-stream-irtf, 46 draft-stream-iab).
STATES = {
    int(o["id"]): {"slug": o["slug"], "type": o["type"]}
    for o in json.loads((Path(__file__).parent / "fixtures/draft-watch/datatracker-states.json").read_text())
}
STATE_ID = {v["slug"]: k for k, v in STATES.items() if v["type"].endswith("/statetype/draft/")}


def datatracker(docs: dict[str, tuple[str, str] | tuple[str, str, list[int]]],
                replaces: dict[str, str | list[str]] | None = None,
                authored: dict[int, list[str]] | None = None, titles: dict[str, str] | None = None,
                page: int = 100):
    """A fake Datatracker: docs maps slug -> (rev, draft state slug[, extra state ids]); replaces
    maps old -> new (or a list of new). List endpoints page `page` objects at a time."""
    replaces = replaces or {}

    def states(slug: str) -> list[str]:
        rev, st, *extra = docs[slug]
        return [f"/api/v1/doc/state/{n}/" for n in [STATE_ID[st], *(extra[0] if extra else [])]]

    def paged(path: str, objs: list[dict]) -> dict:
        off = int(path.split("offset=")[1].split("&")[0]) if "offset=" in path else 0
        nxt = f"{path.split('&offset=')[0]}&offset={off + page}" if off + page < len(objs) else None
        return {"meta": {"next": nxt}, "objects": objs[off:off + page]}

    def get(path: str) -> dict:
        if path.startswith("/api/v1/doc/relateddocument/"):
            target = path.split("target__name=")[1].split("&")[0]
            new = replaces.get(target) or []
            new = [new] if isinstance(new, str) else new
            return paged(path, [{"source": f"/api/v1/doc/document/{n}/"} for n in new])
        if path.startswith("/api/v1/doc/document/?"):
            name = path.split("name=")[1].split("&")[0]
            if name not in docs:
                return {"objects": []}
            return {"objects": [{"rev": docs[name][0], "states": states(name)}]}
        if path.startswith("/api/v1/doc/state/"):
            return STATES[int(path.rstrip("/").rsplit("/", 1)[-1])]
        if path.startswith("/api/v1/doc/documentauthor/"):
            person = int(path.split("person=")[1].split("&")[0])
            mine = (authored or {}).get(person, [])
            return paged(path, [{"document": f"/api/v1/doc/document/{s}/"} for s in mine])
        if path.startswith("/api/v1/doc/document/"):
            slug = path.rstrip("/").rsplit("/", 1)[-1]
            return {"title": (titles or {}).get(slug, ""), "states": states(slug)}
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
            {"draft-acme-widget": ("02", "repl"), "draft-ietf-wg-widget": ("00", "active")},
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
        self.assertEqual(rc, 3)
        self.assertEqual(touched, [])
        self.assertIn("0 of 1 read", out.getvalue())

    def test_signature_moves_with_state(self) -> None:
        a = dw.read(datatracker({"draft-acme-widget": ("02", "active")}), self.pin())
        b = dw.read(datatracker({"draft-acme-widget": ("03", "active")}), self.pin())
        self.assertNotEqual(dw.signature([a]), dw.signature([b]))
        self.assertIn(dw.signature([b]), dw.render([b]))



class Broken(unittest.TestCase):
    """Each input here broke the first version of the tool (2026-11-17); each must stay fixed."""

    def pin(self, **kw: object) -> object:
        return dw.Pin(**{"slug": "draft-acme-widget", "known_rev": "02", "why": "x", **kw})

    def test_withdrawn_is_reported(self) -> None:
        # draft-arkko-map-doi-08 (auth-rm) read as "current" against the live Datatracker.
        for slug in ("auth-rm", "ietf-rm"):
            r = dw.read(datatracker({"draft-acme-widget": ("02", slug, [150])}), self.pin())
            self.assertEqual(r.notes(), ["`draft-acme-widget` is now `withdrawn`"], slug)

    def test_stream_active_does_not_hide_a_replaced_or_withdrawn_draft(self) -> None:
        # draft-clemm-nmrg-dist-intent: draft state repl, IRTF stream state active (id 56).
        for st, word in (("repl", "replaced"), ("auth-rm", "withdrawn"), ("expired", "expired")):
            r = dw.read(datatracker({"draft-acme-widget": ("02", st, [150, 56])}), self.pin())
            self.assertEqual(r.state, word, st)

    def test_sweep_skips_a_replaced_draft_that_holds_a_stream_active_state(self) -> None:
        get = datatracker(
            {"draft-acme-widget": ("02", "active"), "draft-acme-widget-old": ("03", "repl", [56]),
             "draft-acme-widget-ng": ("00", "active", [46])},
            authored={7: ["draft-acme-widget-old", "draft-acme-widget", "draft-acme-widget-ng"]},
            titles={"draft-acme-widget-old": "Widget, first cut", "draft-acme-widget-ng": "Widget, next"},
        )
        r = dw.read(get, self.pin(author_person_id=7, watched_keywords=("widget",)))
        self.assertEqual([s for s, _ in r.related], ["draft-acme-widget-ng"])

    def test_sweep_reads_every_page(self) -> None:
        # Person 21072 has 161 drafts; the first version read the oldest 100 and stopped.
        old = [f"draft-acme-old{i}-thing" for i in range(150)]
        docs = {s: ("00", "expired") for s in old}
        docs |= {"draft-acme-widget": ("02", "active"), "draft-acme-widget-ng": ("00", "active")}
        get = datatracker(docs, authored={7: [*old, "draft-acme-widget", "draft-acme-widget-ng"]},
                          titles={"draft-acme-widget-ng": "Widget, next"}, page=100)
        r = dw.read(get, self.pin(author_person_id=7, watched_keywords=("widget",)))
        self.assertEqual(r.unread, "")
        self.assertEqual([s for s, _ in r.related], ["draft-acme-widget-ng"])

    def test_a_list_without_end_is_unread(self) -> None:
        def endless(path: str) -> dict:
            if path.startswith("/api/v1/doc/relateddocument/"):
                return {"meta": {"next": path + "&x=1"}, "objects": []}
            raise AssertionError(path)

        self.assertIn("pages", dw.read(endless, self.pin()).unread)

    def test_a_split_reports_the_second_successor(self) -> None:
        get = datatracker(
            {"draft-acme-widget": ("02", "repl"), "draft-acme-widget-a": ("00", "active"),
             "draft-acme-widget-b": ("00", "active")},
            replaces={"draft-acme-widget": ["draft-acme-widget-b", "draft-acme-widget-a"]},
        )
        r = dw.read(get, self.pin())
        self.assertEqual(r.slug, "draft-acme-widget-a")
        self.assertIn("`draft-acme-widget-b` (also replaces draft-acme-widget)", " ".join(r.notes()))

    def test_a_document_without_a_draft_state_is_unread(self) -> None:
        def get(path: str) -> dict:
            if path.startswith("/api/v1/doc/relateddocument/"):
                return {"objects": []}
            if path.startswith("/api/v1/doc/document/?"):
                return {"objects": [{"rev": "02", "states": ["/api/v1/doc/state/56/"]}]}
            return STATES[56]

        self.assertIn("one state of type draft", dw.read(get, self.pin()).unread)

    def test_malformed_replies_are_unread_not_a_crash(self) -> None:
        replies = [
            {"objects": [{"source": "/api/v1/doc/document/@everyone/"}]},
            {"objects": "nope"},
            [],
        ]
        for bad in replies:
            r = dw.read(lambda path, bad=bad: bad, self.pin())
            self.assertTrue(r.unread, bad)
            self.assertEqual(r.notes(), [])

    def test_watch_exits_3_without_a_token_when_a_pin_is_unread(self) -> None:
        def down(path: str) -> dict:
            raise urllib.error.URLError("unreachable")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(dw.cmd_watch("t", [self.pin()], False, None, get=down), 3)

    def test_titles_cannot_mention_link_or_break_the_table(self) -> None:
        r = dw.Reading(self.pin(), slug="draft-acme-widget", rev="02", state="active",
                       related=[("draft-acme-x-y", "Hi @someone | see #1 and [x](http://e)")])
        note = r.notes()[0]
        self.assertNotIn("@someone", note)
        self.assertNotIn("#1", note)
        self.assertNotIn(" | ", note)
        self.assertNotIn("[x](", note)

    def test_check_scans_names_in_any_case_after_any_separator(self) -> None:
        self.assertEqual(
            dw.named_drafts("aae_draft-other-thing-03 DRAFT-OTHER-CASE-04 x.draft-dot-name-05 subdraft-no-way-06"),
            {"draft-other-thing", "draft-other-case", "draft-dot-name"},
        )

    def test_check_with_no_file_proves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            cfg = config(Path(d), [PIN])
            self.assertEqual(dw.main(["check", "--config", str(cfg)]), 2)
            self.assertEqual(dw.main(["check", "--config", str(cfg), "--require-pinned"]), 2)

    def test_check_refuses_a_file_it_cannot_read_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = config(Path(d), [PIN])
            f = Path(d) / "blob.bin"
            f.write_bytes(b"\xff\xfe draft-other-thing-03")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(dw.main(["check", "--config", str(cfg), "--require-pinned", str(f)]), 2)
            self.assertIn("UTF-8", out.getvalue())

    def test_unknown_keys_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for drafts, extra in (([{**PIN, "author_personid": 5}], {}), ([PIN], {"unwatched_sha": []}),
                                  ([{**PIN, "author_person_id": 0, "watched_keywords": ["w"]}], {})):
                with self.subTest(drafts=drafts, extra=extra), self.assertRaises(dw.ConfigError):
                    dw.load_config(config(Path(d), drafts, **extra))


class Issue(unittest.TestCase):
    """manage_issue against a recorded `gh`: the issue is open exactly while a pin differs."""

    def run_manage(self, issue: dict | None, readings: list) -> list[list[str]]:
        calls: list[list[str]] = []
        real_gh, real_find = dw.gh, dw.find_issue
        dw.gh = lambda args: calls.append(args) or "https://x/1\n"
        dw.find_issue = lambda repo, title: issue
        try:
            dw.manage_issue("o/r", "t", readings)
        finally:
            dw.gh, dw.find_issue = real_gh, real_find
        return calls

    def moved(self) -> list:
        pin = dw.Pin("draft-acme-widget", "02", "x")
        return [dw.Reading(pin, slug="draft-acme-widget", rev="03", state="active")]

    def test_closed_by_hand_while_a_pin_differs_is_reopened(self) -> None:
        readings = self.moved()
        calls = self.run_manage({"number": 4, "state": "closed", "body": dw.render(readings)}, readings)
        self.assertIn(["issue", "reopen", "4", "-R", "o/r"], calls)
        self.assertFalse(any(c[:2] == ["issue", "edit"] for c in calls))

    def test_unchanged_and_open_is_left_alone(self) -> None:
        readings = self.moved()
        self.assertEqual(self.run_manage({"number": 4, "state": "open", "body": dw.render(readings)}, readings), [])


if __name__ == "__main__":
    unittest.main()
