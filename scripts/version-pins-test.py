#!/usr/bin/env python3
"""Tests for version-pins.py, including the mutation check on this repository.

The mutation check is the one that matters: it copies this repository's tracked
pages into a scratch checkout, makes one tracked pin stale, and requires the
check to go red. A check that stays green on a stale pin guards nothing, and
only running it against a planted fault shows which kind this one is.
Standard library only; run with `python3 scripts/version-pins-test.py`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The unit tests exercise the script; ThisRepository exercises the checkout named by
# VERSION_PINS_ROOT (the caller, when run through the action), else this repository.
ROOT = Path(os.environ.get("VERSION_PINS_ROOT") or HERE.parent).resolve()
SPEC = importlib.util.spec_from_file_location("version_pins", HERE / "version-pins.py")
assert SPEC and SPEC.loader
vp = importlib.util.module_from_spec(SPEC)
sys.modules["version_pins"] = vp
SPEC.loader.exec_module(vp)


def git_repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="version-pins-"))
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


CONFIG = """
repository = "probityai/demo"
registry_pages = { "README.md" = "pypi:demo" }
[[own]]
key = "pypi:demo"
manifest = "pyproject.toml"
pages = ["README.md"]
[family]
"pypi:agent-evidence-vectors" = "0.30.0"
"crates:dsse" = "0.1.6"
"npm:dsse" = "0.1.0"
"action:agent-evidence-vectors" = "0.30.0"
[scan]
historical = ["docs/paper/**"]
"""
PYPROJECT = '[project]\nname = "demo"\nversion = "1.2.3"\n'


class Fixture(unittest.TestCase):
    def run_check(self, readme: str, extra: dict[str, str] | None = None):
        files = {"version-pins.toml": CONFIG, "pyproject.toml": PYPROJECT, "README.md": readme}
        files.update(extra or {})
        root = git_repo(files)
        self.addCleanup(shutil.rmtree, root)
        cfg = vp.load_config(root)
        findings, _ = vp.scan(cfg)
        return root, cfg, findings

    def test_current_pins_pass(self):
        _, _, found = self.run_check(
            "pip install demo==1.2.3\nuvx agent-evidence-vectors==0.30.0\n"
            "cargo add dsse@=0.1.6\nnpm install dsse@0.1.0\n"
            "- uses: probityai/agent-evidence-vectors@v0.30.0\nVersion 1.2.3.\n"
        )
        self.assertEqual(found, [])

    def test_each_stale_form_is_found(self):
        _, _, found = self.run_check(
            "pip install demo==1.2.2\nuvx agent-evidence-vectors==0.29.2\n"
            "cargo add dsse@0.1.5\nnpm i dsse@0.0.9\n"
            "- uses: probityai/agent-evidence-vectors@v0.26.0\nVersion 1.0.0.\n"
            "the `dsse` (0.1.5) crate\n| x | 0.29.0 on PyPI (`agent-evidence-vectors`) |\n"
        )
        self.assertEqual(len(found), 8, "\n".join(map(str, found)))

    def test_link_text_must_name_its_target(self):
        _, _, found = self.run_check(
            "[v0.30.0 release](https://github.com/probityai/agent-evidence-vectors/releases/tag/v0.26.0)\n"
        )
        self.assertTrue(any("link text says 0.30.0" in f.message for f in found), found)

    def test_registry_page_refuses_relative_links_and_write_fixes_them(self):
        root, cfg, found = self.run_check(
            "See [the guide](docs/guide.md) and ![demo](docs/demo.gif).\n",
            {"docs/guide.md": "x\n", "docs/demo.gif": "GIF89a"},
        )
        self.assertEqual(len(found), 2, found)
        vp.write(cfg)
        text = (root / "README.md").read_text()
        self.assertIn("https://github.com/probityai/demo/blob/main/docs/guide.md", text)
        self.assertIn("https://raw.githubusercontent.com/probityai/demo/main/docs/demo.gif", text)

    def test_own_link_to_a_missing_file_is_found(self):
        _, _, found = self.run_check("[gone](https://github.com/probityai/demo/blob/main/docs/gone.md)\n")
        self.assertTrue(any("does not hold" in f.message for f in found), found)

    def test_historical_pages_and_keep_markers_are_exempt(self):
        _, _, found = self.run_check(
            "pip install demo==1.0.0 <!-- version-pins: keep -->\n",
            {"docs/paper/README.md": "uvx agent-evidence-vectors==0.12.0\n",
             "CHANGELOG.md": "uvx agent-evidence-vectors==0.1.0\n"},
        )
        self.assertEqual(found, [])

    def test_write_renders_every_pin_from_its_owner(self):
        root, cfg, _ = self.run_check("pip install demo==1.0.0\nuvx agent-evidence-vectors==0.29.2\n")
        changed, remaining = vp.write(cfg)
        self.assertEqual((changed, remaining), (2, []))
        self.assertIn("demo==1.2.3", (root / "README.md").read_text())

    def test_a_bumped_manifest_turns_the_old_pins_red(self):
        root, _, found = self.run_check("pip install demo==1.2.3\n")
        self.assertEqual(found, [])
        (root / "pyproject.toml").write_text(PYPROJECT.replace("1.2.3", "1.3.0"))
        findings, _ = vp.scan(vp.load_config(root))
        self.assertEqual(len(findings), 1)

    def test_refresh_leaves_a_parseable_lock(self):
        root, cfg, _ = self.run_check("pip install demo==1.2.3\n")
        with mock.patch.object(vp, "registry_latest", return_value="0.31.0"):
            vp.refresh(cfg)
        text = (root / "version-pins.toml").read_text()
        self.assertIn('"pypi:agent-evidence-vectors" = "0.31.0"\n', text)
        vp.load_config(root)

    def test_two_owners_for_one_package_is_a_config_error(self):
        bad = CONFIG + '\n[[own]]\nkey = "pypi:agent-evidence-vectors"\nmanifest = "pyproject.toml"\n'
        root = git_repo({"version-pins.toml": bad, "pyproject.toml": PYPROJECT})
        self.addCleanup(shutil.rmtree, root)
        with self.assertRaises(vp.ConfigError):
            vp.load_config(root)


FORMULA = """class AgentEvidenceVectors < Formula
  url "https://files.pythonhosted.org/packages/de/ef/abc/agent_evidence_vectors-{v}.tar.gz"
  sha256 "{sha}"

  resource "rfc8785" do
    url "https://files.pythonhosted.org/packages/ef/2f/x/rfc8785-0.1.4.tar.gz"
    sha256 "{other}"
  end
end
"""


class Formulas(unittest.TestCase):
    def setUp(self):
        text = FORMULA.format(v="0.23.0", sha="1" * 64, other="2" * 64)
        self.root = git_repo({"version-pins.toml": CONFIG, "pyproject.toml": PYPROJECT,
                              "Formula/agent-evidence-vectors.rb": text})
        self.addCleanup(shutil.rmtree, self.root)

    def test_a_stale_formula_url_is_found_and_write_leaves_it(self):
        cfg = vp.load_config(self.root, "version-pins.toml")
        cfg.include.append("Formula/*.rb")
        findings, _ = vp.scan(cfg)
        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].replacement)
        self.assertIn("formulas", findings[0].message)
        before = (self.root / "Formula/agent-evidence-vectors.rb").read_text()
        vp.write(cfg)
        self.assertEqual((self.root / "Formula/agent-evidence-vectors.rb").read_text(), before)

    def test_formulas_moves_url_and_sha_together_and_leaves_resources(self):
        cfg = vp.load_config(self.root)
        url = "https://files.pythonhosted.org/packages/aa/bb/new/agent_evidence_vectors-0.30.0.tar.gz"
        with mock.patch.object(vp, "sdist_of", return_value=(url, "3" * 64)):
            moved = vp.formulas(cfg, out=open(os.devnull, "w"))
        self.assertEqual(moved, ["agent-evidence-vectors"])
        text = (self.root / "Formula/agent-evidence-vectors.rb").read_text()
        self.assertIn(url, text)
        self.assertIn("3" * 64, text)
        self.assertIn("2" * 64, text)  # the resource's sha256 is untouched
        self.assertIn("rfc8785-0.1.4.tar.gz", text)
        with mock.patch.object(vp, "sdist_of", side_effect=AssertionError("no fetch when current")):
            self.assertEqual(vp.formulas(vp.load_config(self.root), out=open(os.devnull, "w")), [])


class Grace(unittest.TestCase):
    NOW = vp.datetime(2026, 11, 3, 12, tzinfo=vp.UTC)

    def entry(self):
        return vp.Entry(registry="pypi", name="demo", version="0.3.3", source="lock", own=False)

    def verdict(self, history):
        with mock.patch.object(vp, "release_history", return_value=history):
            return vp.lag_in_grace(self.entry(), max(history, key=vp._vkey), now=self.NOW)

    def test_one_release_behind_inside_a_day_is_grace(self):
        h = {"0.3.3": self.NOW - vp.timedelta(days=3), "0.3.4": self.NOW - vp.timedelta(hours=2)}
        self.assertIn("grace", self.verdict(h))

    def test_one_release_behind_older_than_a_day_is_not(self):
        h = {"0.3.3": self.NOW - vp.timedelta(days=3), "0.3.4": self.NOW - vp.timedelta(hours=25)}
        self.assertIsNone(self.verdict(h))

    def test_two_releases_behind_is_not_even_when_both_are_new(self):
        h = {"0.3.3": self.NOW - vp.timedelta(days=3), "0.3.4": self.NOW - vp.timedelta(hours=3),
             "0.3.5": self.NOW - vp.timedelta(hours=1)}
        self.assertIsNone(self.verdict(h))

    def test_registry_report_counts_grace_as_agreeing_and_short_as_red(self):
        root = git_repo({"version-pins.toml": 'repository = "probityai/demo"\n[family]\n"pypi:demo" = "0.3.3"\n'})
        self.addCleanup(shutil.rmtree, root)
        cfg = vp.load_config(root)
        out = open(os.devnull, "w")
        with mock.patch.object(vp, "registry_latest", return_value="0.3.4"), \
                mock.patch.object(vp, "lag_in_grace", return_value="inside the grace"), \
                mock.patch("sys.stdout", out):
            self.assertEqual(vp.registry_report(cfg), 0)
        with mock.patch.object(vp, "registry_latest", return_value="0.3.4"), \
                mock.patch.object(vp, "lag_in_grace", return_value=None), \
                mock.patch("sys.stdout", out):
            self.assertEqual(vp.registry_report(cfg), 1)


class ThisRepository(unittest.TestCase):
    """The real pages pass, and a planted stale pin turns the check red."""

    def test_pages_agree(self):
        cfg = vp.load_config(ROOT)
        findings, _ = vp.scan(cfg)
        self.assertEqual(findings, [], "\n".join(map(str, findings)))

    def test_mutation_a_stale_pin_is_caught(self):
        cfg = vp.load_config(ROOT)
        rules = vp.pin_rules(cfg.entries)
        target = None
        for rel in vp.tracked_files(ROOT):
            if not vp.matches(rel, cfg.include) or vp.matches(rel, cfg.historical):
                continue
            if vp.matches(rel, cfg.skip):
                continue
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for rule in rules:
                m = rule.pattern.search(text)
                if m and m.group(1) == rule.entry.version and rule.line_kind is None:
                    target = (rel, text, m.span(1))
                    break
            if target:
                break
        if target is None:
            self.fail("no tracked pin on any page to mutate; the check is vacuous here")
        rel, text, (start, end) = target
        stale = "0.0.1" if text[start:end] != "0.0.1" else "0.0.2"
        scratch = Path(tempfile.mkdtemp(prefix="version-pins-mutant-"))
        self.addCleanup(shutil.rmtree, scratch)
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(scratch / "r")], check=True)
        mutant = scratch / "r"
        shutil.copy2(ROOT / vp.CONFIG, mutant / vp.CONFIG)
        for item in vp.load_config(ROOT).entries:
            if item.manifest:
                (mutant / item.manifest).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / item.manifest, mutant / item.manifest)
        (mutant / rel).write_text(text[:start] + stale + text[end:], encoding="utf-8")
        subprocess.run(["git", "-C", str(mutant), "add", "-A"], check=True)
        done = subprocess.run(
            [sys.executable, str(HERE / "version-pins.py"), "check", "--root", str(mutant)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 1, f"the check stayed green on {rel}:\n{done.stdout}")
        self.assertTrue(re.search(re.escape(stale), done.stdout), done.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
