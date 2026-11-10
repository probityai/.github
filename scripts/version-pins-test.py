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


class ManifestVersions(unittest.TestCase):
    """A manifest names its version directly, or through hatch's dynamic version file."""

    def read(self, pyproject: str, files: dict[str, str] | None = None) -> str:
        root = git_repo({"pkg/pyproject.toml": pyproject, **(files or {})})
        self.addCleanup(shutil.rmtree, root)
        return vp.read_manifest(root, "pkg/pyproject.toml")

    def test_a_static_version_is_read(self):
        self.assertEqual(self.read('[project]\nname = "a"\nversion = "1.2.3"\n'), "1.2.3")

    def test_a_hatch_dynamic_version_is_read_from_its_file(self):
        text = '[project]\nname = "a"\ndynamic = ["version"]\n[tool.hatch.version]\npath = "src/a/__init__.py"\n'
        self.assertEqual(
            self.read(text, {"pkg/src/a/__init__.py": '"""doc"""\n__version__ = "0.2.0"\n'}), "0.2.0"
        )

    def test_a_dynamic_version_with_no_readable_source_is_a_config_error(self):
        text = '[project]\nname = "a"\ndynamic = ["version"]\n[tool.hatch.version]\npath = "src/a/__init__.py"\n'
        with self.assertRaises(vp.ConfigError):
            self.read(text, {"pkg/src/a/__init__.py": "x = 1\n"})
        with self.assertRaises(vp.ConfigError):
            self.read(text)  # the named file is missing
        with self.assertRaises(vp.ConfigError):
            self.read('[project]\nname = "a"\ndynamic = ["version"]\n')


TABLE_CONFIG = """
repository = "probityai/demo"
[[own]]
key = "pypi:demo"
manifest = "pyproject.toml"
[[own]]
key = "pypi:demo-cases"
manifest = "cases/pyproject.toml"
[family]
"pypi:other" = "0.9.0"
"pypi:shared" = "2.0.0"
"crates:shared" = "3.0.0"
"npm:shared" = "4.0.0"
"""
TABLE_FILES = {
    "version-pins.toml": TABLE_CONFIG,
    "pyproject.toml": PYPROJECT,
    "cases/pyproject.toml": '[project]\nname = "demo-cases"\nversion = "0.5.0"\n',
}
TABLE_HEAD = "| package | what it is | version | downloads |\n| --- | --- | :---: | :---: |\n"


class TableVersions(unittest.TestCase):
    """A bold version in a package's table row is a pin: found, rewritten, and kept bold."""

    def scan(self, rows: str):
        root = git_repo({**TABLE_FILES, "README.md": TABLE_HEAD + rows})
        self.addCleanup(shutil.rmtree, root)
        cfg = vp.load_config(root)
        findings, _ = vp.scan(cfg)
        return root, cfg, findings

    def test_a_stale_bold_version_is_found_and_write_keeps_the_bold(self):
        root, cfg, found = self.scan("| [demo](packages/demo/README.md) | a tool | **1.2.0** | - |\n")
        self.assertEqual(len(found), 1, found)
        self.assertIn("table version names 1.2.0", found[0].message)
        changed, remaining = vp.write(cfg)
        self.assertEqual((changed, remaining), (1, []))
        self.assertIn("| **1.2.3** | - |", (root / "README.md").read_text())
        self.assertEqual(vp.scan(vp.load_config(root))[0], [])

    def test_a_current_bold_version_passes(self):
        _, _, found = self.scan("| [demo](packages/demo/README.md) | a tool | **1.2.3** | - |\n")
        self.assertEqual(found, [])

    def test_a_package_named_in_another_column_does_not_claim_the_row(self):
        _, _, found = self.scan("| [other](x.md) | works with demo and demo-cases | **0.9.0** | - |\n")
        self.assertEqual(found, [])
        _, _, found = self.scan("| [other](x.md) | works with demo | **1.2.3** | - |\n")
        self.assertEqual([f.message.split()[0] for f in found], ["pypi:other"], found)

    def test_a_name_that_prefixes_another_follows_its_own_owner(self):
        _, cfg, found = self.scan(
            "| [demo](packages/demo/README.md) | a tool | **1.0.0** | - |\n"
            "| [demo-cases](packages/demo-cases/README.md) | its cases | **0.4.0** | - |\n"
        )
        self.assertEqual(
            sorted(f.message.split()[0] for f in found), ["pypi:demo", "pypi:demo-cases"], found
        )
        vp.write(cfg)
        text = (cfg.root / "README.md").read_text()
        self.assertIn("| a tool | **1.2.3** |", text)
        self.assertIn("| its cases | **0.5.0** |", text)

    def test_one_name_on_three_registries_reads_the_registry_cell(self):
        _, cfg, found = self.scan(
            "| package | registry | version |\n| --- | --- | --- |\n"
            "| [shared](a.md) | PyPI | **1.0.0** |\n"
            "| shared | crates.io | **1.0.0** |\n"
            "| shared | npm | **1.0.0** |\n"
        )
        self.assertEqual(
            sorted(f.message.split()[0] for f in found),
            ["crates:shared", "npm:shared", "pypi:shared"],
            found,
        )
        vp.write(cfg)
        text = (cfg.root / "README.md").read_text()
        self.assertIn("| PyPI | **2.0.0** |", text)
        self.assertIn("| crates.io | **3.0.0** |", text)
        self.assertIn("| npm | **4.0.0** |", text)

    def test_a_package_released_only_on_github_is_held_to_its_owner(self):
        cfg = TABLE_CONFIG + '[[own]]\nkey = "github:kit"\nmanifest = "kit/pyproject.toml"\ntag = "kit-v{version}"\n'
        root = git_repo({**TABLE_FILES, "version-pins.toml": cfg,
                         "kit/pyproject.toml": '[project]\nname = "kit"\nversion = "0.1.0"\n',
                         "README.md": TABLE_HEAD + "| [kit](kit/README.md) | replays a record | **0.0.9** | not on PyPI |\n"})
        self.addCleanup(shutil.rmtree, root)
        findings, _ = vp.scan(vp.load_config(root))
        self.assertEqual([f.message.split()[0] for f in findings], ["github:kit"], findings)

    def test_the_keep_marker_exempts_a_row(self):
        _, _, found = self.scan("| [demo](x.md) | a tool | **1.0.0** | - | <!-- version-pins: keep -->\n")
        self.assertEqual(found, [])

    def test_a_bold_number_that_is_not_a_version_cell_is_ignored(self):
        _, _, found = self.scan("| [demo](x.md) | **1.0.0** is old | 1.2.3 | - |\n")
        self.assertEqual(found, [])


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

    def test_settle_hours_widen_the_grace(self):
        h = {"0.3.3": self.NOW - vp.timedelta(days=3), "0.3.4": self.NOW - vp.timedelta(hours=25)}
        with mock.patch.object(vp, "release_history", return_value=h):
            got = vp.lag_in_grace(self.entry(), "0.3.4", now=self.NOW, settle=vp.timedelta(hours=25))
        self.assertIn("49 h grace", got)

    def test_settled_latest_skips_a_release_younger_than_settle_hours(self):
        h = {"0.3.3": self.NOW - vp.timedelta(days=3), "0.3.4": self.NOW - vp.timedelta(hours=30),
             "0.3.5": self.NOW - vp.timedelta(hours=3)}
        cfg = vp.Config(root=Path("."), repository="probityai/demo", entries=[], include=[], historical=[],
                        skip=[], registry_pages={}, link_ref="main", settle=vp.timedelta(hours=25))
        with mock.patch.object(vp, "registry_latest", return_value="0.3.5"), \
                mock.patch.object(vp, "release_history", return_value=h):
            self.assertEqual(vp.settled_latest(cfg, self.entry(), now=self.NOW), "0.3.4")
        cfg.settle = vp.timedelta(0)
        with mock.patch.object(vp, "registry_latest", return_value="0.3.5"):
            self.assertEqual(vp.settled_latest(cfg, self.entry(), now=self.NOW), "0.3.5")

    def test_settled_latest_never_moves_a_lock_backwards(self):
        h = {"0.3.3": self.NOW - vp.timedelta(hours=3)}
        cfg = vp.Config(root=Path("."), repository="probityai/demo", entries=[], include=[], historical=[],
                        skip=[], registry_pages={}, link_ref="main", settle=vp.timedelta(hours=25))
        with mock.patch.object(vp, "registry_latest", return_value="0.3.3"), \
                mock.patch.object(vp, "release_history", return_value=h):
            self.assertIsNone(vp.settled_latest(cfg, self.entry(), now=self.NOW))

    def test_two_releases_behind_is_not_even_when_both_are_new(self):
        h = {"0.3.3": self.NOW - vp.timedelta(days=3), "0.3.4": self.NOW - vp.timedelta(hours=3),
             "0.3.5": self.NOW - vp.timedelta(hours=1)}
        self.assertIsNone(self.verdict(h))

    def _attestation(self, repo):
        import base64, json
        payload = {"predicate": {"buildDefinition": {"externalParameters": {"workflow": {"repository": f"https://github.com/{repo}"}}}}}
        env = base64.b64encode(json.dumps(payload).encode()).decode()
        return {"attestations": [{"bundle": {"dsseEnvelope": {"payload": env}}}]}

    def test_a_token_release_is_accepted_when_github_attested_its_digest(self):
        e = vp.Entry(registry="pypi", name="demo", version="0.3.3", source="lock", own=True, publisher="org/repo")
        files = {"urls": [{"filename": "demo-0.3.3.tar.gz", "digests": {"sha256": "a" * 64}}]}

        def fetch(url, **kwargs):
            if url.endswith("/json"):
                return files
            if "/integrity/" in url:
                return None
            self.assertIn("/repos/org/repo/attestations/sha256:" + "a" * 64, url)
            return self._attestation("org/repo")

        with mock.patch.object(vp, "fetch_json", side_effect=fetch):
            self.assertEqual(vp.publisher_of(e, "0.3.3"), "org/repo")

    def test_a_release_with_neither_pypi_provenance_nor_an_attestation_is_unread(self):
        e = vp.Entry(registry="pypi", name="demo", version="0.3.3", source="lock", own=True, publisher="org/repo")
        files = {"urls": [{"filename": "demo-0.3.3.tar.gz", "digests": {"sha256": "b" * 64}}]}

        def fetch(url, **kwargs):
            return files if url.endswith("/json") else None

        with mock.patch.object(vp, "fetch_json", side_effect=fetch):
            self.assertIsNone(vp.publisher_of(e, "0.3.3"))

    def test_an_attestation_from_another_repository_names_that_repository(self):
        e = vp.Entry(registry="pypi", name="demo", version="0.3.3", source="lock", own=True, publisher="org/repo")
        files = {"urls": [{"filename": "demo-0.3.3.tar.gz", "digests": {"sha256": "c" * 64}}]}

        def fetch(url, **kwargs):
            if url.endswith("/json"):
                return files
            return None if "/integrity/" in url else self._attestation("someone/else")

        with mock.patch.object(vp, "fetch_json", side_effect=fetch):
            self.assertEqual(vp.publisher_of(e, "0.3.3"), "someone/else")

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
