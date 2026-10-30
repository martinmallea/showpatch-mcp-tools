"""Tests de la captura DMX a disco: escritura, resumen, CSV y sink del monitor."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dmx_capture import DmxCapture, export_csv, iter_frames, read_meta, summary  # noqa: E402
from core.dmx_monitor import DmxMonitor, artnet_packet  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def capture(self, frames=((1, [255, 0]), (1, [128, 0]), (2, [0, 7]))):
        monitor = DmxMonitor()
        path = self.dir / "toma.dmxcap"
        cap = DmxCapture(path)
        monitor.set_sink(cap.write)
        for universe, values in frames:
            monitor.feed(artnet_packet(universe, values))
        cap.close()
        return path


class TestCapture(Base):
    def test_writes_meta_and_frames(self):
        path = self.capture()
        meta = read_meta(path)
        self.assertIn("created_at", meta)
        frames = list(iter_frames(path))
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0]["channels"][:2], (255, 0))
        self.assertEqual(frames[2]["universe"], 2)

    def test_compression_is_small(self):
        path = self.capture()
        raw = 3 * 512
        self.assertLess(path.stat().st_size, raw / 4)

    def test_summary(self):
        info = summary(self.capture())
        self.assertEqual(info["frames"], 3)
        self.assertEqual(len(info["universes"]), 2)
        universo_1 = next(u for u in info["universes"] if u["universe"] == 1)
        self.assertEqual(universo_1["frames"], 2)
        self.assertEqual(universo_1["active_channels"], 1)  # sólo ch1 sale de cero
        self.assertEqual(universo_1["peak"], 255)

    def test_summary_of_empty_file(self):
        path = self.dir / "vacia.dmxcap"
        DmxCapture(path).close()
        info = summary(path)
        self.assertEqual(info["frames"], 0)
        self.assertEqual(info["universes"], [])

    def test_export_csv(self):
        path = self.capture()
        out = self.dir / "universo1.csv"
        result = export_csv(path, 1, out)
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["channels"], 1)
        lineas = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lineas[0], "t,ch1")
        self.assertTrue(lineas[1].startswith("0.0,") or lineas[1].startswith("0,"))

    def test_export_missing_universe_raises(self):
        path = self.capture()
        with self.assertRaises(ValueError):
            export_csv(path, 99, self.dir / "x.csv")

    def test_list_captures(self):
        path = self.capture()
        from core.dmx_capture import list_captures

        found = list_captures(self.dir)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], path.name)
        self.assertEqual(found[0]["frames"], 3)
        self.assertEqual(found[0]["universes"], [1, 2])

    def test_list_captures_missing_dir(self):
        from core.dmx_capture import list_captures

        self.assertEqual(list_captures(self.dir / "no-existe"), [])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_meta(self.dir / "no.dmxcap")


class TestSink(Base):
    def test_sink_can_be_removed(self):
        monitor = DmxMonitor()
        path = self.dir / "sink.dmxcap"
        cap = DmxCapture(path)
        monitor.set_sink(cap.write)
        monitor.feed(artnet_packet(1, [1]))
        monitor.set_sink(None)
        monitor.feed(artnet_packet(1, [2]))
        cap.close()
        self.assertEqual(len(list(iter_frames(path))), 1)

    def test_capture_survives_corrupt_line(self):
        path = self.capture()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("no es json\n")
        self.assertEqual(len(list(iter_frames(path))), 3)


if __name__ == "__main__":
    unittest.main()
