"""Tests del registro de lecciones y de su inyección en los briefs."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.cli import render_brief  # noqa: E402
from orchestrator.plan import load_plan  # noqa: E402
from tools import lessons as store  # noqa: E402


class LessonsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "lessons.jsonl"
        self._original = store.DEFAULT_PATH
        store.DEFAULT_PATH = self.path

    def tearDown(self):
        store.DEFAULT_PATH = self._original
        self._tmp.cleanup()


class TestAppend(LessonsBase):
    def test_add_and_read(self):
        entry = store.add("SUB-QA", "Un golden puede estar mal", "Audita el vector antes de tocar producción.", wp="WP-01")
        self.assertEqual(entry["role"], "SUB-QA")
        entries = store.read()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Un golden puede estar mal")

    def test_requires_title_and_detail(self):
        with self.assertRaises(ValueError):
            store.add("SUB-QA", "", "detalle")
        with self.assertRaises(ValueError):
            store.add("SUB-QA", "titulo", "   ")

    def test_limits(self):
        with self.assertRaises(ValueError):
            store.add("SUB-QA", "x" * 200, "detalle")
        with self.assertRaises(ValueError):
            store.add("SUB-QA", "titulo", "y" * 700)

    def test_corrupt_line_is_ignored(self):
        self.path.write_text('{"role":"SUB-QA","title":"ok","detail":"d"}\nnot json\n\n', encoding="utf-8")
        self.assertEqual(len(store.read()), 1)


class TestQuery(LessonsBase):
    def test_recent_filters_by_role_and_includes_global(self):
        store.add("SUB-QA", "qa uno", "detalle")
        store.add("SUB-PARSER", "parser uno", "detalle")
        store.add("ALL", "global uno", "detalle")
        titles = [entry["title"] for entry in store.recent("SUB-QA")]
        self.assertIn("qa uno", titles)
        self.assertIn("global uno", titles)
        self.assertNotIn("parser uno", titles)

    def test_recent_honours_limit_and_order(self):
        for index in range(7):
            store.add("SUB-QA", f"lección {index}", "detalle")
        recent = store.recent("SUB-QA", limit=3)
        self.assertEqual([e["title"] for e in recent], ["lección 4", "lección 5", "lección 6"])

    def test_missing_file_is_empty(self):
        store.DEFAULT_PATH = Path("no_existe.jsonl")
        self.assertEqual(store.read(), [])
        self.assertEqual(store.format_for_brief("SUB-QA"), "")


class TestBriefInjection(LessonsBase):
    def test_brief_includes_role_lessons(self):
        store.add("SUB-PARSER", "q busca por nombre", "No filtra por fabricante: pagina y filtra en cliente.", wp="WP-11")
        brief = render_brief(load_plan(), {"work_packages": {}}, "WP-02")
        self.assertIn("Lecciones previas de SUB-PARSER", brief)
        self.assertIn("q busca por nombre", brief)

    def test_brief_without_lessons_has_no_section(self):
        brief = render_brief(load_plan(), {"work_packages": {}}, "WP-03")
        self.assertNotIn("Lecciones previas", brief)


if __name__ == "__main__":
    unittest.main()
