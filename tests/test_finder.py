"""Tests del fingerprinting DMX: roles, footprint y degradación sin datos."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.finder import DMX_CHANNELS, analyze_raw_dmx_stream, fingerprint  # noqa: E402


def _frame(**overrides) -> list[int]:
    frame = [0] * DMX_CHANNELS
    for index, value in overrides.items():
        frame[int(index[1:])] = value
    return frame


def synthetic_rig(steps: int = 8) -> list[list[int]]:
    """Rig de 6 canales: pan 16-bit, tilt 16-bit, dimmer y strobe."""
    frames = []
    for step in range(steps):
        pan = step * 9000
        tilt = step * 3000
        frame = [0] * DMX_CHANNELS
        frame[0], frame[1] = pan >> 8, pan & 0xFF
        frame[2], frame[3] = tilt >> 8, tilt & 0xFF
        frame[4] = 40 + step * 25
        frame[6] = 255 if step % 2 else 0
        frames.append(frame)
    return frames


class TestRoles(unittest.TestCase):
    def test_detects_pan_tilt_dimmer_strobe(self):
        result = fingerprint(synthetic_rig())
        roles = result["roles"]
        self.assertEqual(roles.get("pan"), 1)
        self.assertEqual(roles.get("pan_fine"), 2)
        self.assertEqual(roles.get("tilt"), 3)
        self.assertEqual(roles.get("tilt_fine"), 4)
        self.assertEqual(roles.get("dimmer"), 5)
        self.assertEqual(roles.get("shutter"), 7)
        self.assertGreaterEqual(result["confidence"], 0.7)

    def test_footprint_is_even_and_covers_active_range(self):
        result = fingerprint(synthetic_rig())
        self.assertEqual(result["channel_count"], 8)  # canales 1..7 → 8
        self.assertTrue(result["evidence"])

    def test_candidates_ranked_and_bounded(self):
        result = fingerprint(synthetic_rig())
        self.assertTrue(1 <= len(result["candidates"]) <= 3)
        scores = [c["score"] for c in result["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))
        self.assertTrue(all(c["reason"] for c in result["candidates"]))


class TestDegradation(unittest.TestCase):
    def test_single_frame_does_not_raise_and_warns(self):
        result = fingerprint([_frame(c0=10)])
        self.assertEqual(result["channel_count"], 2)
        self.assertLessEqual(result["confidence"], 0.5)
        self.assertTrue(any("fotograma" in w.lower() for w in result["warnings"]))

    def test_all_zero_frame(self):
        result = fingerprint([[0] * DMX_CHANNELS])
        self.assertEqual(result["channel_count"], 0)
        self.assertEqual(result["confidence"], 0.0)
        self.assertTrue(result["warnings"])

    def test_short_frame_is_padded_with_warning(self):
        result = fingerprint([[10, 20, 30]])
        self.assertTrue(any("canales" in w for w in result["warnings"]))
        self.assertEqual(result["channel_count"], 4)

    def test_garbage_values_are_clamped(self):
        result = fingerprint([[999, -5, 300, "x"]])
        self.assertIsInstance(result["channel_count"], int)
        self.assertTrue(result["warnings"])

    def test_none_and_empty(self):
        self.assertEqual(fingerprint(None)["channel_count"], 0)
        self.assertEqual(fingerprint([])["channel_count"], 0)

    def test_alias_accepts_single_frame(self):
        self.assertEqual(
            analyze_raw_dmx_stream([0] * DMX_CHANNELS)["channel_count"],
            fingerprint([[0] * DMX_CHANNELS])["channel_count"],
        )


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        self.assertEqual(fingerprint(synthetic_rig()), fingerprint(synthetic_rig()))


if __name__ == "__main__":
    unittest.main()
