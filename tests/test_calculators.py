"""Tests de las tres calculadoras: DMX, color y daltonismo."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.color_calc import convert, cmy_to_rgb, hex_to_rgb, hsv_to_rgb, rgb_to_cmy, rgb_to_rgbw  # noqa: E402
from core.colorblind import confusable_pairs, contrast_ratio, name_color, simulate, simulate_all  # noqa: E402
from core.dmx_calc import (  # noqa: E402
    address_range,
    capacity,
    dip_switches,
    dmx_from_percent,
    find_conflicts,
    next_free,
    percent_from_dmx,
    summarize,
    universe_of,
)


class TestDmxRanges(unittest.TestCase):
    def test_range_is_inclusive(self):
        self.assertEqual(address_range(1, 1), (1, 1))
        self.assertEqual(address_range(10, 31), (10, 40))

    def test_cannot_spill_out_of_universe(self):
        with self.assertRaises(ValueError):
            address_range(500, 20)

    def test_universe_of_global_address(self):
        self.assertEqual(universe_of(1), 1)
        self.assertEqual(universe_of(512), 1)
        self.assertEqual(universe_of(513), 2)

    def test_capacity(self):
        self.assertEqual(capacity(31), 16)
        self.assertEqual(capacity(512), 1)


class TestDipSwitches(unittest.TestCase):
    def test_known_addresses(self):
        self.assertEqual(dip_switches(1), [1])
        self.assertEqual(dip_switches(5), [1, 3])  # 1 + 4
        self.assertEqual(dip_switches(10), [2, 4])  # 2 + 8
        self.assertEqual(dip_switches(512), [10])

    def test_rejects_zero(self):
        with self.assertRaises(ValueError):
            dip_switches(0)


class TestPatch(unittest.TestCase):
    def test_next_free_skips_used(self):
        self.assertEqual(next_free([(1, 31)]), 32)
        self.assertEqual(next_free([(1, 10), (12, 20)], footprint=2), 21)

    def test_next_free_uses_gap(self):
        self.assertEqual(next_free([(1, 10), (40, 50)], footprint=5), 11)

    def test_next_free_returns_none_when_full(self):
        self.assertIsNone(next_free([(1, 512)], footprint=1))

    def test_conflicts_detects_overlap(self):
        fixtures = [
            {"id": "11", "universe": 1, "address": 1, "footprint": 20},
            {"id": "12", "universe": 1, "address": 15, "footprint": 10},
        ]
        conflicts = find_conflicts(fixtures)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["overlap"], [15, 20])
        self.assertEqual(conflicts[0]["channels"], 6)

    def test_adjacent_is_not_conflict(self):
        fixtures = [
            {"id": "11", "universe": 1, "address": 1, "footprint": 10},
            {"id": "12", "universe": 1, "address": 11, "footprint": 10},
        ]
        self.assertEqual(find_conflicts(fixtures), [])

    def test_different_universes_never_conflict(self):
        fixtures = [
            {"id": "11", "universe": 1, "address": 1, "footprint": 30},
            {"id": "12", "universe": 2, "address": 1, "footprint": 30},
        ]
        self.assertEqual(find_conflicts(fixtures), [])

    def test_summarize_reports_usage_and_conflicts(self):
        show = {
            "fixtures": [
                {"id": "11", "patch": {"universe": 1, "address": 1, "dmx_footprint": 32}},
                {"id": "12", "patch": {"universe": 1, "address": 20, "dmx_footprint": 32}},
                {"id": "13", "patch": {"universe": 2, "address": 100, "dmx_footprint": 10}},
            ]
        }
        report = summarize(show)
        self.assertTrue(report["has_conflicts"])
        self.assertEqual(report["fixture_count"], 3)
        universo_1 = next(row for row in report["universes"] if row["universe"] == 1)
        self.assertGreater(universo_1["channels_used"], 0)
        self.assertEqual(universo_1["next_free_address"], 52)


class TestPercent(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(percent_from_dmx(255), 100.0)
        self.assertEqual(percent_from_dmx(0), 0.0)
        self.assertEqual(dmx_from_percent(50), 128)

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            percent_from_dmx(256)
        with self.assertRaises(ValueError):
            dmx_from_percent(101)


class TestColor(unittest.TestCase):
    def test_primary_colors(self):
        self.assertEqual(rgb_to_cmy([255, 0, 0]), (0.0, 100.0, 100.0))
        self.assertEqual(cmy_to_rgb([0, 100, 100]), (255, 0, 0))

    def test_hex_roundtrip(self):
        self.assertEqual(hex_to_rgb("#ff8800"), (255, 136, 0))
        self.assertEqual(convert("#ff8800")["hex"], "#ff8800")
        self.assertEqual(hex_to_rgb("#f80"), (255, 136, 0))

    def test_hsv_roundtrip(self):
        self.assertEqual(hsv_to_rgb(0, 100, 100), (255, 0, 0))
        self.assertEqual(convert([255, 0, 0])["hsv"][0], 0.0)
        self.assertAlmostEqual(convert([255, 0, 0])["hsv"][1], 100.0)

    def test_rgbw_extracts_white(self):
        self.assertEqual(rgb_to_rgbw([255, 255, 255]), (0, 0, 0, 255))
        self.assertEqual(rgb_to_rgbw([200, 100, 100]), (100, 0, 0, 100))

    def test_percent_and_cmy_input_forms(self):
        self.assertEqual(convert({"percent": [100, 0, 0]})["rgb"], [255, 0, 0])
        self.assertEqual(convert({"cmy": [0, 100, 100]})["hex"], "#ff0000")

    def test_invalid_color_raises(self):
        with self.assertRaises(ValueError):
            hex_to_rgb("#12345")
        with self.assertRaises(ValueError):
            convert({"nada": 1})


class TestColorblind(unittest.TestCase):
    def test_gray_stays_gray(self):
        for mode in ("protanopia", "deuteranopia", "tritanopia"):
            simulated = simulate([128, 128, 128], mode)
            self.assertLessEqual(max(simulated) - min(simulated), 2)

    def test_simulate_all_has_three_modes(self):
        values = simulate_all([255, 0, 0])
        self.assertEqual(set(values), {"protanopia", "deuteranopia", "tritanopia"})

    def test_magenta_and_gray_confusion_under_deuteranopia(self):
        """Par real medido: con deuteranopía, magenta y gris quedan a distancia ~11."""
        pairs = confusable_pairs([[160, 0, 160], [128, 128, 128]], "deuteranopia")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["names"], ["magenta", "gris"])
        self.assertLess(pairs[0]["simulated_distance"], 40)

    def test_distinct_colors_are_not_flagged(self):
        self.assertEqual(confusable_pairs([[255, 255, 255], [0, 0, 0]], "deuteranopia"), [])

    def test_names(self):
        self.assertEqual(name_color([255, 0, 0]), "rojo")
        self.assertEqual(name_color([0, 0, 0]), "negro")
        self.assertEqual(name_color([255, 255, 255]), "blanco")
        self.assertIn(name_color([255, 140, 0]), ("naranja", "ámbar"))

    def test_contrast(self):
        self.assertGreater(contrast_ratio([0, 0, 0], [255, 255, 255]), 20)
        self.assertAlmostEqual(contrast_ratio([120, 120, 120], [120, 120, 120]), 1.0)

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            simulate([0, 0, 0], "ceguera_total")


if __name__ == "__main__":
    unittest.main()
