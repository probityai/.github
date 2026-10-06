"""Mutation controls for the public navigation contract."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_profile", ROOT / "scripts/check_profile.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ProfileControls(unittest.TestCase):
    def setUp(self):
        self.catalog = {"components": [
            {"id": f"tool-{n}", "task": f"Task {n}", "display_name": f"Tool {n}",
             "docs_url": f"https://github.com/probityai/tool-{n}/blob/{'a' * 40}/README.md"}
            for n in range(8)
        ]}
        self.rows = [f"| {item['task']} | [{item['display_name']}]({item['docs_url']}) |"
                     for item in self.catalog["components"]]
        self.front_door = "\n".join(f"[{name}](https://probityai.github.io/agent-evidence-atlas/{name})"
                                     for name in ("start.html", "start.md", "llms.txt", "lab.html"))
        self.text = "\n".join(self.rows) + "\n" + self.front_door

    def test_complete_profile(self):
        self.assertEqual(len(CHECK.validate_profile(self.text, self.catalog)), 12)

    def test_reviewed_component_growth_needs_no_fixed_count(self):
        item = {"id": "tool-8", "task": "Task 8", "display_name": "Tool 8",
                "docs_url": f"https://github.com/probityai/tool-8/blob/{'a' * 40}/README.md"}
        catalog = {"components": [*self.catalog["components"], item]}
        text = self.text + f"\n| {item['task']} | [{item['display_name']}]({item['docs_url']}) |"
        self.assertEqual(len(CHECK.validate_profile(text, catalog)), 13)

    def test_duplicate_component_identity_refuses(self):
        self.catalog["components"][1]["id"] = self.catalog["components"][0]["id"]
        with self.assertRaises(ValueError):
            CHECK.validate_profile(self.text, self.catalog)

    def test_malformed_reviewed_catalog_refuses(self):
        for catalog in (None, [], {}, {"components": []}, {"components": {}},
                        {"components": [None]}, {"components": [{"id": "x"}]}):
            with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                CHECK.validate_profile(self.text, catalog)

    def test_empty_or_nontext_component_fields_refuse(self):
        for field in ("id", "task", "display_name", "docs_url"):
            for value in ("", " ", None, True, 1, []):
                item = {**self.catalog["components"][0], field: value}
                catalog = {"components": [item, *self.catalog["components"][1:]]}
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CHECK.validate_profile(self.text, catalog)

    def test_missing_duplicate_and_extra_tasks_refuse(self):
        for text in (self.text.replace(self.rows[0], ""),
                     self.text.replace(self.rows[0], self.rows[1]), self.text + "\n" + self.rows[0]):
            with self.subTest(text=text), self.assertRaises(ValueError):
                CHECK.validate_profile(text, self.catalog)

    def test_changed_task_identity_or_source_refuses(self):
        for old, new in (("Task 0", "Other task"), ("Tool 0", "Other tool"), ("a" * 40, "b" * 40)):
            with self.subTest(field=old), self.assertRaises(ValueError):
                CHECK.validate_profile(self.text.replace(old, new, 1), self.catalog)

    def test_discovery_surface_required(self):
        for name in ("start.html", "start.md", "llms.txt", "lab.html"):
            with self.subTest(surface=name), self.assertRaises(ValueError):
                CHECK.validate_profile(self.text.replace(name, "missing"), self.catalog)

    def test_nonpublic_or_authenticated_links_refuse(self):
        for url in ("http://github.com/probityai", "https://example.com/private", "file:///tmp/data",
                    "https://user@github.com/probityai", "https://github.com.evil.example/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                CHECK.validate_profile(self.text + f"\n[extra]({url})", self.catalog)

    def test_only_exact_source_urls_map_to_raw_bytes(self):
        source = self.catalog["components"][0]["docs_url"]
        self.assertEqual(CHECK.readback_target(source), source.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/"))
        for url in (source.replace("a" * 40, "main"), "https://probityai.github.io/agent-evidence-atlas/start.md"):
            self.assertEqual(CHECK.readback_target(url), url)


if __name__ == "__main__":
    unittest.main()
