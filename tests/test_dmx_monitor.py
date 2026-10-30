"""Tests del monitor DMX: parseo de tramas, fps, grabación y API."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dmx_monitor import (  # noqa: E402
    DmxMonitor,
    artnet_packet,
    parse_artnet,
    parse_sacn,
    sacn_packet,
)


class TestArtNet(unittest.TestCase):
    def test_parses_universe_and_channels(self):
        packet = artnet_packet(3, [10, 20, 255])
        frame = parse_artnet(packet)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.universe, 3)
        self.assertEqual(frame.channels[:3], (10, 20, 255))
        self.assertEqual(len(frame.channels), 512)
        self.assertEqual(frame.protocol, "artnet")

    def test_rejects_garbage(self):
        self.assertIsNone(parse_artnet(b""))
        self.assertIsNone(parse_artnet(b"no es artnet"))
        self.assertIsNone(parse_artnet(b"Art-Net\x00" + b"\x00" * 10))

    def test_high_universe(self):
        frame = parse_artnet(artnet_packet(1024, [1]))
        self.assertEqual(frame.universe, 1024)


class TestSacn(unittest.TestCase):
    def test_parses_universe_and_channels(self):
        frame = parse_sacn(sacn_packet(7, [1, 2, 3]))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.universe, 7)
        self.assertEqual(frame.channels[:3], (1, 2, 3))
        self.assertEqual(frame.protocol, "sacn")

    def test_rejects_wrong_preamble(self):
        self.assertIsNone(parse_sacn(b"\x00\x11" + b"x" * 200))


class TestMonitor(unittest.TestCase):
    def setUp(self):
        self.monitor = DmxMonitor()

    def test_counts_and_snapshot(self):
        self.monitor.feed(artnet_packet(1, [255, 0, 7]))
        self.monitor.feed(artnet_packet(1, [255, 0, 9]))
        self.monitor.feed(sacn_packet(2, [1]))
        snap = self.monitor.snapshot()
        self.assertEqual(snap["frames_total"], 3)
        self.assertEqual(len(snap["universes"]), 2)
        first = snap["universes"][0]
        self.assertEqual(first["universe"], 1)
        self.assertEqual(first["active"], 2)
        self.assertEqual(first["peak"], 255)
        self.assertGreaterEqual(first["fps"], 2)

    def test_full_includes_channels(self):
        self.monitor.feed(artnet_packet(1, [5]))
        snap = self.monitor.snapshot(full=True)
        self.assertEqual(len(snap["universes"][0]["channels"]), 512)

    def test_ignores_unknown_packets(self):
        self.assertIsNone(self.monitor.feed(b"basura"))
        self.assertEqual(self.monitor.snapshot()["frames_total"], 0)

    def test_record_start_stop(self):
        self.monitor.record_start()
        for _ in range(3):
            self.monitor.feed(artnet_packet(1, [1]))
        self.assertTrue(self.monitor.recording()["on"])
        result = self.monitor.record_stop()
        self.assertEqual(result["frames"], 3)
        self.assertEqual(result["universes"], [1])
        self.assertFalse(self.monitor.recording()["on"])

    def test_record_stop_without_start(self):
        result = self.monitor.record_stop()
        self.assertEqual(result["frames"], 0)


class TestApi(unittest.TestCase):
    def test_payload_shape(self):
        from web.app import dmx_live_payload, dmx_record_payload

        self.monitor_module_guard = None
        payload = dmx_live_payload()
        self.assertIn("universes", payload)
        self.assertIn("listening", payload)

        started = dmx_record_payload("start")
        self.assertTrue(started["recording"]["on"])
        stopped = dmx_record_payload("stop")
        self.assertFalse(stopped["recording"]["on"])

    def test_bad_action(self):
        from web.app import dmx_record_payload

        with self.assertRaises(ValueError):
            dmx_record_payload("borrar")


if __name__ == "__main__":
    unittest.main()
