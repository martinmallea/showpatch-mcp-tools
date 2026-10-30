"""Tests del índice de fixtures y de su uso como último recurso del parser."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.fixture_library as library  # noqa: E402
from core.parsers import split_fixture_type_string  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_equivalent_forms_collapse(self):
        self.assertEqual(library.normalize("MAC Aura XB"), library.normalize("MAC_Aura_XB"))
        self.assertEqual(library.normalize("MAC Aura XB"), library.normalize("mac aura xb"))
        self.assertEqual(library.normalize("AE-2D-5R"), "ae2d5r")

    def test_empty_and_none(self):
        self.assertEqual(library.normalize(""), "")
        self.assertEqual(library.normalize(None), "")


class TestIndex(unittest.TestCase):
    def test_index_available(self):
        info = library.summary()
        if not info["available"]:
            self.skipTest("índice no generado: python bridge.py fixtures --sync")
        self.assertGreater(info["count"], 1000)
        self.assertEqual(len(info["library_version"]), 10)  # dd-mm-yyyy

    def test_search_returns_bounded_rows(self):
        rows = library.search("robe", "pointe", limit=5)
        self.assertLessEqual(len(rows), 5)
        for row in rows:
            self.assertIn("robe", library.normalize(row["manufacturer"]))

    def test_resolve_with_explicit_mode(self):
        rows = library.search("robe", "pointe", limit=20)
        if not rows:
            self.skipTest("Robe Pointe no está en el índice")
        for row in rows:
            hit = library.resolve(row["manufacturer"], row["model"], row["mode"])
            self.assertIsNotNone(hit)
            self.assertEqual(hit["channels"], row["channels"])
            self.assertFalse(hit["ambiguous"])

    def test_resolve_unknown_is_none(self):
        self.assertIsNone(library.resolve("NoExisteMarca", "NoExisteModelo"))

    def test_resolve_marks_ambiguity(self):
        rows = library.search(manufacturer="robe", model="pointe", limit=20)
        counts = {row["channels"] for row in rows}
        if len(counts) < 2:
            self.skipTest("hace falta un modelo con varios modos")
        hit = library.resolve(rows[0]["manufacturer"], rows[0]["model"])
        self.assertTrue(hit["ambiguous"])
        self.assertGreater(len(hit["options"]), 1)


class TestParserFallback(unittest.TestCase):
    def test_parser_uses_library_as_last_resort(self):
        payload = {
            "source": "test",
            "library_version": "30-10-2026",
            "count": 1,
            "fixtures": [
                {"id": 999001, "manufacturer": "ZZTest", "model": "Ultra", "mode": "7ch",
                 "channels": 42, "file": "ZZTest_Ultra_7ch.hed"}
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mini_library.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            original = library.DEFAULT_PATH
            library.DEFAULT_PATH = path
            try:
                result = split_fixture_type_string("ZZTest Ultra")
                self.assertEqual(result["manufacturer"], "ZZTest")
                self.assertEqual(result["channel_count"], 42)
                self.assertEqual(result["channel_count_source"], "library")
            finally:
                library.DEFAULT_PATH = original

    def test_known_cases_still_win_before_library(self):
        """El contrato manda: regex y diccionarios resuelven antes."""
        result = split_fixture_type_string("Robe Pointe 24ch Mode 1")
        self.assertEqual(result["channel_count"], 24)
        self.assertEqual(result["channel_count_source"], "regex")

    def test_missing_index_does_not_break_parser(self):
        original = library.DEFAULT_PATH
        library.DEFAULT_PATH = Path("no_existe_este_indice.json")
        try:
            result = split_fixture_type_string("MarcaRara ModeloRaro")
            self.assertIsNone(result["channel_count"])
            self.assertEqual(result["channel_count_source"], "unresolved")
        finally:
            library.DEFAULT_PATH = original


if __name__ == "__main__":
    unittest.main()
