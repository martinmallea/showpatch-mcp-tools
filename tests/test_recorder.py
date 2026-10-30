"""Tests del grabador y del reproductor (sin dormir en tiempo real)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import recorder  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, name="take1", events=((0.0, "Go Sequence 1"), (1.5, "Go Sequence 2"))):
        path = recorder.new_recording(name, self.dir)
        rec = recorder.Recorder(path)
        for at, command in events:
            rec.append("/gma3/cmd", [command], at=at)
        return path


class TestRecording(Base):
    def test_roundtrip_meta_and_events(self):
        path = self.make()
        record = recorder.load(path)
        self.assertEqual(record["meta"]["name"], "take1")
        self.assertEqual(len(record["events"]), 2)
        self.assertEqual(record["events"][1]["args"], ["Go Sequence 2"])
        self.assertAlmostEqual(record["duration"], 1.5)

    def test_recorder_counts_and_timestamps(self):
        path = recorder.new_recording("x", self.dir)
        rec = recorder.Recorder(path)
        event = rec.append("/gma3/cmd", ["Clear"], at=2.0)
        self.assertEqual(event["t"], 2.0)
        self.assertEqual(rec.count, 1)

    def test_corrupt_lines_are_ignored(self):
        path = self.make()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("esto no es json\n")
        self.assertEqual(len(recorder.load(path)["events"]), 2)

    def test_slugify(self):
        self.assertEqual(recorder.slugify("Pase de focos / v2"), "Pase-de-focos-v2")
        self.assertEqual(recorder.slugify("***"), "take")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            recorder.load(self.dir / "no.jsonl")

    def test_summary(self):
        summary = recorder.summarize(self.make())
        self.assertEqual(summary["events"], 2)
        self.assertEqual(summary["addresses"]["/gma3/cmd"], 2)


class TestPlan(Base):
    def test_relative_times_and_speed(self):
        record = recorder.load(self.make())
        schedule = recorder.plan(record["events"], speed=2.0)
        self.assertEqual([item["at"] for item in schedule], [0.0, 0.75])

    def test_loops_offset_by_span_and_gap(self):
        record = recorder.load(self.make())
        schedule = recorder.plan(record["events"], speed=1.0, loops=2, gap=0.5)
        self.assertEqual([item["loop"] for item in schedule], [0, 0, 1, 1])
        self.assertEqual([item["at"] for item in schedule], [0.0, 1.5, 2.0, 3.5])

    def test_empty(self):
        self.assertEqual(recorder.plan([]), [])

    def test_invalid_speed_and_loops(self):
        with self.assertRaises(ValueError):
            recorder.plan([{"t": 0, "address": "/x", "args": []}], speed=0)
        with self.assertRaises(ValueError):
            recorder.plan([{"t": 0, "address": "/x", "args": []}], loops=0)


class TestReplay(Base):
    def test_dry_run_never_sends(self):
        record = recorder.load(self.make())
        sleeps = []
        result = recorder.replay(record, sleep=sleeps.append)
        self.assertEqual(result["sent"], 2)
        self.assertFalse(result["live"])
        self.assertTrue(all(not item["sent"] for item in result["results"]))
        self.assertEqual(sleeps, [1.5])  # sólo espera entre eventos
        self.assertEqual(len(result["results"]), 2)

    def test_sleep_matches_schedule(self):
        record = recorder.load(self.make())
        sleeps = []
        recorder.replay(record, speed=1.0, sleep=sleeps.append)
        self.assertEqual(sleeps, [1.5])

    def test_custom_sender_receives_commands(self):
        record = recorder.load(self.make())
        seen = []
        result = recorder.replay(
            record,
            sleep=lambda _: None,
            sender=lambda address, args: (seen.append((address, args[0])), {"sent": True, "bytes": 40})[1],
        )
        self.assertEqual(seen, [("/gma3/cmd", "Go Sequence 1"), ("/gma3/cmd", "Go Sequence 2")])
        self.assertEqual(result["sent"], 2)


class TestMcpIntegration(Base):
    def test_osc_send_records_when_env_set(self):
        import os

        import mcp_server.tools as tools

        path = recorder.new_recording("integracion", self.dir)
        os.environ["SHOWPATCH_RECORD"] = str(path)
        try:
            tools.call_tool("osc.send", {"ip": "127.0.0.1", "address": "/gma3/cmd", "args": ["Clear"]})
        finally:
            os.environ.pop("SHOWPATCH_RECORD", None)
            tools._RECORDER = None
        record = recorder.load(path)
        self.assertEqual(len(record["events"]), 1)
        self.assertEqual(record["events"][0]["args"], ["Clear"])
        self.assertEqual(record["events"][0]["address"], "/gma3/cmd")


if __name__ == "__main__":
    unittest.main()
