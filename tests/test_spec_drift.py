"""Spec drift across the family (scripts/spec_drift.py), on throwaway checkouts."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("spec_drift", ROOT / "scripts/spec_drift.py")
DRIFT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIFT  # the dataclasses in it resolve their module by name
SPEC.loader.exec_module(DRIFT)

HOME = "probityai/agent-evidence-vectors"
CONSUMER = "probityai/probity"
GITHUB_URI = "https://probityai.github.io/agent-evidence-vectors/predicate/v1/"
W3ID_URI = "https://w3id.org/agent-evidence/predicate/v1/"

CONFIG = f"""
[family]
"{HOME}" = "agent-evidence-vectors"
"{CONSUMER}" = "probity"

[scan]
suffixes = [".md", ".yml"]
skip = ["corpora/*/cases/*", "tests/*"]

[[check]]
id = "predicate-uri-registered"
home = "{HOME}"
description = "registered"

[[check]]
id = "w3id-predicate-page"
home = "{HOME}"
description = "paged"

[[check]]
id = "corpus-id-published"
home = "{HOME}"
description = "published"
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class SpecDriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.config = base / "spec-drift.toml"
        write(self.config, CONFIG)
        self.family = base / "family"
        self.home = self.family / "agent-evidence-vectors"
        self.consumer = self.family / "probity"
        write(self.home / "spec/predicates/REGISTRY.md", "## Defined here\n\n### `predicate/v1/observed-effect`\n")
        write(self.home / "pages/predicate/v1/done-receipt/index.html", "<html></html>")
        write(self.home / "corpora/REGISTRY.toml", '[[corpus]]\nid = "vectors-a"\n')
        write(self.home / "README.md", f"Type `{GITHUB_URI}observed-effect`.\n")
        write(self.consumer / "README.md", f"We emit {GITHUB_URI}observed-effect and {W3ID_URI}done-receipt.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_as(self, repo, checkout):
        args = ["--self", str(checkout), "--self-repo", repo, "--family", str(self.family), "--config", str(self.config)]
        return DRIFT.main(args)

    def test_a_family_that_agrees_passes_for_every_caller(self):
        self.assertEqual(self.run_as(CONSUMER, self.consumer), 0)
        self.assertEqual(self.run_as(HOME, self.home), 0)

    def test_an_unregistered_uri_in_a_consumer_fails_the_consumer_and_the_home(self):
        write(self.consumer / "docs/emit.md", f"{GITHUB_URI}renamed-effect\n")
        self.assertEqual(self.run_as(CONSUMER, self.consumer), 1)
        self.assertEqual(self.run_as(HOME, self.home), 1)

    def test_a_w3id_uri_needs_its_page(self):
        write(self.consumer / "docs/emit.md", f"{W3ID_URI}done-contract\n")
        self.assertEqual(self.run_as(CONSUMER, self.consumer), 1)

    def test_a_corpus_id_passed_to_the_action_must_be_published(self):
        write(self.consumer / ".github/workflows/ci.yml", "with:\n  corpus: vectors-b\n")
        self.assertEqual(self.run_as(CONSUMER, self.consumer), 1)
        write(self.consumer / ".github/workflows/ci.yml", "with:\n  corpus: vectors-a\n")
        self.assertEqual(self.run_as(CONSUMER, self.consumer), 0)

    def test_case_data_and_tests_are_not_drift(self):
        write(self.home / "corpora/vectors-a/cases/wrong/README.md", f"{GITHUB_URI}wrong-type\n")
        write(self.consumer / "tests/fake.md", "--corpus vectors-made-up\n")
        self.assertEqual(self.run_as(HOME, self.home), 0)

    def test_a_finding_in_a_third_repository_is_reported_not_failed(self):
        third = "probityai/agent-evidence-matrix"
        write(self.config, CONFIG.replace('"probity"\n', f'"probity"\n"{third}" = "agent-evidence-matrix"\n', 1))
        write(self.family / "agent-evidence-matrix/README.md", "--corpus vectors-gone\n")
        self.assertEqual(self.run_as(CONSUMER, self.consumer), 0)
        self.assertEqual(self.run_as(HOME, self.home), 1)

    def test_a_missing_checkout_is_an_error_not_a_pass(self):
        (self.consumer / "README.md").unlink()
        self.consumer.rmdir()
        self.assertEqual(self.run_as(HOME, self.home), 2)

    def test_a_check_without_an_implementation_is_refused(self):
        write(self.config, CONFIG + '\n[[check]]\nid = "made-up"\nhome = "' + HOME + '"\ndescription = "x"\n')
        self.assertEqual(self.run_as(HOME, self.home), 2)

    def test_the_committed_configuration_loads(self):
        config = DRIFT.load_config()
        self.assertEqual({check["id"] for check in config["check"]}, set(DRIFT.CHECKS))


if __name__ == "__main__":
    unittest.main()
