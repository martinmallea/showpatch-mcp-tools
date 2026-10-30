"""Tests de la integración con Notion: payloads, bundle y orden de llamadas."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import notion_sync  # noqa: E402


class FakeTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, payload):
        self.calls.append((method, path, payload))
        if path == "/pages" and payload and payload.get("parent", {}).get("page_id"):
            return {"id": "page-1"}
        if path == "/data_sources":
            return {"id": f"ds-{len(self.calls)}"}
        return {"id": f"pg-{len(self.calls)}"}


class TestRows(unittest.TestCase):
    def test_work_packages_have_state_and_owner(self):
        rows = notion_sync.work_package_rows()
        self.assertGreaterEqual(len(rows), 15)
        first = rows[0]
        for key in ("ID", "Titulo", "Estado", "Owner", "Gate", "Evidencia"):
            self.assertIn(key, first)
        self.assertIn(first["Estado"], {"pending", "in_progress", "done", "failed", "blocked"})

    def test_done_packages_have_evidence(self):
        rows = notion_sync.work_package_rows()
        done = [row for row in rows if row["Estado"] == "done"]
        self.assertTrue(done)
        self.assertTrue(any(row["Evidencia"] for row in done))

    def test_lessons_rows(self):
        rows = notion_sync.lesson_rows()
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all("Titulo" in row and "Rol" in row for row in rows))

    def test_releases_parsed(self):
        versions = [row["Version"] for row in notion_sync.release_rows()]
        self.assertIn("1.6.0", versions)


class TestPayloads(unittest.TestCase):
    def test_title_and_rich_truncate(self):
        self.assertLessEqual(len(notion_sync.Notion.title("x" * 3000)["title"][0]["text"]["content"]), 1900)
        self.assertLessEqual(len(notion_sync.Notion.rich("y" * 3000)["rich_text"][0]["text"]["content"]), 1900)

    def test_select_none(self):
        self.assertEqual(notion_sync.Notion.select(""), {"select": None})

    def test_props_have_title(self):
        self.assertIn("ID", notion_sync.ROADMAP_PROPS)
        self.assertEqual(notion_sync.ROADMAP_PROPS["ID"], {"title": {}})


class TestBundle(unittest.TestCase):
    def test_bundle_files_and_csv_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = notion_sync.build_bundle(Path(tmp))
            self.assertIn("roadmap.csv", result["files"])
            header = (Path(tmp) / "roadmap.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(header.startswith("ID,Titulo,Estado,Owner"))
            self.assertIn("00 Portada.md", result["files"])

            lessons = (Path(tmp) / "lecciones.csv").read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lessons), 2)


class TestApply(unittest.TestCase):
    def setUp(self):
        notion_sync.SLEEP = 0
        self._tmp = tempfile.TemporaryDirectory()
        self.ids = Path(self._tmp.name) / "ids.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_apply_creates_page_then_databases_then_items(self):
        fake = FakeTransport()
        result = notion_sync.apply("token", "parent-123", transport=fake, ids_file=self.ids)

        self.assertEqual(result["page_id"], "page-1")
        self.assertEqual(fake.calls[0][1], "/pages")
        self.assertEqual(fake.calls[0][2]["parent"], {"page_id": "parent-123"})

        data_sources = [call for call in fake.calls if call[1] == "/data_sources"]
        self.assertEqual(len(data_sources), 3)
        self.assertEqual(data_sources[0][2]["title"][0]["text"]["content"], "Roadmap")

        items = [call for call in fake.calls if call[1] == "/pages" and "database_id" in call[2]["parent"]]
        self.assertEqual(len(items), result["items"])
        self.assertGreaterEqual(len(items), 15)

        saved = json.loads(self.ids.read_text(encoding="utf-8"))
        self.assertEqual(saved["page"], "page-1")
        self.assertIn("roadmap", saved)

    def test_apply_reuses_cached_ids(self):
        notion_sync.apply("token", "parent-123", transport=FakeTransport(), ids_file=self.ids)
        second = FakeTransport()
        notion_sync.apply("token", "parent-123", transport=second, ids_file=self.ids)
        self.assertEqual([call[1] for call in second.calls if call[1] == "/data_sources"], [])

    def test_dry_run_writes_payloads(self):
        exit_code = notion_sync.main(["--dry-run"])
        self.assertEqual(exit_code, 0)
        out = ROOT / "exports" / "notion_payloads.json"
        self.assertTrue(out.is_file())
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("work_packages", data)


if __name__ == "__main__":
    unittest.main()
