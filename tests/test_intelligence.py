"""Tests de geometría: bearing, offset de modelo, herradura idempotente y afín."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.intelligence import adapt, bearing_to, horseshoe, normalize_pan, pan_for, style_profile  # noqa: E402
from core.schema_validator import validate_show  # noqa: E402


def fixture(fid: str, manufacturer: str, model: str, x: float = 0.0, y: float = 0.0, z: float = 4.0,
            rotation: dict | None = None) -> dict:
    position = {
        "x": x, "y": y, "z": z, "unit": "meters",
        "rotation": rotation or {"pan_deg": 0.0, "tilt_deg": 0.0, "roll_deg": 0.0},
    }
    return {
        "id": fid,
        "name": f"Fixture_{fid}",
        "type": {"manufacturer": manufacturer, "model": model},
        "patch": {"universe": 1, "address": 1},
        "position": position,
        "semantic": {"role": "beam", "zone": "stage_left", "bearing_deg": None,
                     "calculated_pan": None, "pan_offset_deg": 0.0},
    }


def rig(count: int = 6) -> dict:
    return {
        "schema_version": "1.0.0",
        "source": {"system": "grandMA3", "extracted_at": "2026-10-30T14:00:00Z"},
        "fixtures": [
            fixture(str(11 + i), "Robe", "Pointe", x=-3.0 + i, y=0.0)
            for i in range(count)
        ],
    }


class TestBearing(unittest.TestCase):
    def test_cardinal_directions(self):
        self.assertAlmostEqual(bearing_to({"x": -5.0, "y": 0.0}), 0.0)
        self.assertAlmostEqual(bearing_to({"x": 0.0, "y": 5.0}), -90.0)
        self.assertAlmostEqual(bearing_to({"x": 5.0, "y": 0.0}), 180.0)
        self.assertAlmostEqual(bearing_to({"x": 0.0, "y": -5.0}), 90.0)

    def test_target_equals_position_is_zero(self):
        self.assertEqual(bearing_to({"x": 1.0, "y": 1.0}, (1.0, 1.0)), 0.0)

    def test_matches_contract_horseshoe_convention(self):
        """El contrato calcula atan2(-y, -x) para apuntar al centro."""
        for x, y in ((-5.0, 0.0), (-3.0, 4.0), (0.0, 5.0)):
            expected = round(math.degrees(math.atan2(-y, -x)), 2)
            self.assertAlmostEqual(bearing_to({"x": x, "y": y}), expected, places=2)


class TestPan(unittest.TestCase):
    def test_known_model_applies_offset(self):
        led = fixture("21", "Robe", "LEDBeam 12", x=-5.0, y=0.0)
        computed = pan_for(led)
        self.assertEqual(computed["fixture_key"], "Robe_LEDBeam_12")
        self.assertEqual(computed["pan_offset_deg"], 90.0)
        self.assertAlmostEqual(computed["calculated_pan"], 90.0)

    def test_unknown_model_is_auditable(self):
        unknown = fixture("22", "Chino", "Mega Beam 9999", x=-5.0, y=0.0)
        computed = pan_for(unknown)
        self.assertFalse(computed["model_known"])
        self.assertEqual(computed["calculated_pan"], 0.0)

    def test_offsets_can_be_disabled(self):
        led = fixture("23", "Robe", "LEDBeam 12", x=-5.0, y=0.0)
        self.assertAlmostEqual(pan_for(led, apply_offsets=False)["calculated_pan"], 0.0)

    def test_wrapping_stays_in_physical_range(self):
        self.assertEqual(normalize_pan(300.0), -240.0)
        self.assertEqual(normalize_pan(-300.0), 240.0)
        self.assertEqual(normalize_pan(271.0), -269.0)


class TestHorseshoe(unittest.TestCase):
    def test_positions_on_arc_and_semantics_written(self):
        result = horseshoe(rig(5), radius=5.0, start_deg=180.0, end_deg=0.0)
        self.assertEqual(validate_show(result, post_parser=False), [])
        xs = [f["position"]["x"] for f in result["fixtures"]]
        ys = [f["position"]["y"] for f in result["fixtures"]]
        self.assertAlmostEqual(xs[0], -5.0, places=3)  # 180° → stage left
        self.assertAlmostEqual(xs[2], 0.0, places=3)  # 90° → centro del arco
        self.assertAlmostEqual(ys[2], 5.0, places=3)
        for f in result["fixtures"]:
            radius = math.hypot(f["position"]["x"], f["position"]["y"])
            self.assertAlmostEqual(radius, 5.0, places=2)
            self.assertIsNotNone(f["semantic"]["bearing_deg"])
            self.assertIsNotNone(f["semantic"]["calculated_pan"])

    def test_preserves_height_and_rotation(self):
        show = rig(3)
        show["fixtures"][0]["position"]["z"] = 7.25
        show["fixtures"][0]["position"]["rotation"] = {"pan_deg": 12.0, "tilt_deg": 0.0, "roll_deg": 0.0}
        result = horseshoe(show)
        self.assertEqual(result["fixtures"][0]["position"]["z"], 7.25)
        self.assertEqual(result["fixtures"][0]["position"]["rotation"]["pan_deg"], 12.0)
        self.assertEqual(result["fixtures"][0]["position"]["mount_type_source"], "default")

    def test_idempotent(self):
        once = horseshoe(rig(5))
        twice = horseshoe(once)
        self.assertEqual(
            [f["position"] for f in once["fixtures"]],
            [f["position"] for f in twice["fixtures"]],
        )

    def test_single_fixture_is_returned_untouched_with_warning(self):
        show = rig(1)
        result = horseshoe(show)
        self.assertEqual(result["fixtures"][0]["position"], show["fixtures"][0]["position"])
        self.assertTrue(result["metadata"]["intelligence"]["warnings"])


class TestAdapt(unittest.TestCase):
    def test_scale_rotate_translate(self):
        show = rig(1)
        show["fixtures"][0]["position"].update({"x": -3.0, "y": 0.0, "z": 4.0})
        result = adapt(show, {"scale_x": 0.5, "scale_y": 0.5, "rotate_z": 90.0, "offset_x": 1.0})
        position = result["fixtures"][0]["position"]
        self.assertAlmostEqual(position["x"], 1.0, places=3)
        self.assertAlmostEqual(position["y"], -1.5, places=3)
        self.assertAlmostEqual(position["z"], 4.0, places=3)
        self.assertEqual(result["metadata"]["intelligence"]["operation"], "affine")

    def test_does_not_mutate_input(self):
        show = rig(2)
        before = show["fixtures"][0]["position"]["x"]
        adapt(show, {"scale_x": 2.0})
        self.assertEqual(show["fixtures"][0]["position"]["x"], before)

    def test_output_validates(self):
        self.assertEqual(validate_show(adapt(rig(3), {"scale_x": 1.2}), post_parser=False), [])


class TestStyleProfile(unittest.TestCase):
    def test_deterministic_and_shaped(self):
        show = rig(4)
        for f in show["fixtures"]:
            f["capabilities"] = {"color_system": "CMY"}
        first = style_profile(show)
        self.assertEqual(first, style_profile(show))
        self.assertEqual(first["programmer_dna"]["density_cluster"], "Compact-Rig")
        self.assertEqual(first["programmer_dna"]["color_space_preference"], "CMY_Dominant")
        self.assertEqual(first["rig"]["fixture_count"], 4)

    def test_empty_rig(self):
        profile = style_profile({"fixtures": []})
        self.assertEqual(profile["rig"]["fixture_count"], 0)
        self.assertEqual(profile["programmer_dna"]["color_space_preference"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
