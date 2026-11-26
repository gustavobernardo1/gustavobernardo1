import copy
import tempfile
import unittest
from pathlib import Path
from scripts.update_conjectura import START, END, refresh, validate, render

URL = "https://github.com/gustavobernardo1/conjectura/tree/research/results"
STATUS = {"mathematical": "proved", "formal": "not-started",
          "novelty": "no-prior-resolution-found", "external_review": "ai-reviewed"}


def fixture():
    return {"generated": {"revision": "abc", "sources_committed": True, "sources": {}},
            "public": {"schema_version": 1, "active_investigations": [],
                       "primary_investigation": None,
                       "established_original_discoveries": {
                           "lemmas": 0, "theorems": 0, "counterexamples": 0,
                           "other": 0, "total": 0},
                       "resolved_conjectures": {"proved": 0, "disproved": 0, "total": 0},
                       "latest_established_original_discovery": None,
                       "latest_formally_verified_original_contribution": None,
                       "research_catalogue_url": URL, "reviewed_results_url": URL}}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = [self.root / f for f in ("README.md", "README.pt-BR.md")]
        self.original = "before\n" + START + "\nold\n" + END + "\nafter\n"
        for path in self.paths:
            path.write_text(self.original, encoding="utf-8")

    def test_bilingual_and_idempotent(self):
        data = fixture()
        self.assertEqual(refresh(data, self.root), 2)
        self.assertIn("Conjectures resolved", self.paths[0].read_text())
        self.assertIn("Conjecturas resolvidas", self.paths[1].read_text())
        for path in self.paths:
            self.assertTrue(path.read_text().startswith("before\n"))
            self.assertTrue(path.read_text().endswith("\nafter\n"))
        self.assertEqual(refresh(data, self.root), 0)

    def test_invalid_contract_preserves_readmes(self):
        for field, value in (("schema_version", 2), ("primary_investigation", {}),
                             ("established_original_discoveries", {"lemmas": 3})):
            data = fixture()
            data["public"][field] = value
            with self.assertRaises(ValueError):
                refresh(data, self.root)
            self.assertTrue(all(p.read_text() == self.original for p in self.paths))

    def test_missing_marker_preserves_other_file(self):
        self.paths[1].write_text("unmanaged")
        with self.assertRaises(ValueError):
            refresh(fixture(), self.root)
        self.assertEqual(self.paths[0].read_text(), self.original)

    def test_new_result(self):
        data = fixture()
        p = data["public"]
        p["established_original_discoveries"].update(theorems=1, total=1)
        p["resolved_conjectures"].update(proved=1, total=1)
        p["latest_established_original_discovery"] = {
            "id": "MD-0008", "title": "A new theorem", "url": URL, "status": copy.copy(STATUS)}
        self.assertEqual(refresh(data, self.root), 2)
        self.assertIn("| 0 | 1 | 0 | 0 |", self.paths[0].read_text())
        self.assertIn("MD-0008", self.paths[1].read_text())
        p["latest_established_original_discovery"]["status"]["mathematical"] = "candidate-proof"
        with self.assertRaises(ValueError):
            validate(data)

    def test_url_rejected_and_markdown_escaped(self):
        data = fixture()
        p = data["public"]
        p["research_catalogue_url"] = "https://example.org/"
        with self.assertRaises(ValueError):
            validate(data)
        p["research_catalogue_url"] = URL
        record = {"id": "CJ-0002", "title": "<img> [title]", "url": URL, "status": STATUS}
        p["active_investigations"] = [record]
        p["primary_investigation"] = record
        out = render(validate(data), "en")
        self.assertIn("&lt;img&gt;", out)
        self.assertNotIn("<img>", out)


if __name__ == "__main__":
    unittest.main()
