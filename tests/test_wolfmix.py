"""Tests del puente Wolfmix: codificación MIDI, mapa y dry-run."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridges.wolfmix_bridge import WolfmixBridge, load_mapping, resolve, write_example  # noqa: E402
from core.midi import MidiOut, cc, note_off, note_on, program_change  # noqa: E402


class TestEncoding(unittest.TestCase):
    def test_cc(self):
        self.assertEqual(cc(0, 1, 127), 0xB0017F)
        self.assertEqual(cc(15, 10, 0), 0xBF0A00)

    def test_notes(self):
        self.assertEqual(note_on(0, 36, 100), 0x902464)
        self.assertEqual(note_off(1, 36), 0x812400)

    def test_program_change(self):
        self.assertEqual(program_change(2, 5), 0xC20005)

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            cc(16, 1, 1)
        with self.assertRaises(ValueError):
            cc(0, 200, 1)
        with self.assertRaises(ValueError):
            note_on(0, 1, 200)


class TestMidiOut(unittest.TestCase):
    def test_dry_run_records_only(self):
        out = MidiOut(dry_run=True)
        self.assertTrue(out.send(cc(0, 1, 64)))
        self.assertEqual(out.hex_sent(), ["B00140"])
        out.close()

    def test_rejects_bad_message(self):
        out = MidiOut(dry_run=True)
        with self.assertRaises(ValueError):
            out.send(-1)


class TestMapping(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "mapping.json"

    def tearDown(self):
        self._tmp.cleanup()

    def escribir(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return self.path

    def test_valid_mapping(self):
        self.escribir({"channel": 1, "actions": {"go": {"type": "note", "number": 40}}})
        mapping = load_mapping(self.path)
        self.assertEqual(mapping["channel"], 1)
        self.assertEqual(resolve(mapping, "go"), ("note", 40, 1))

    def test_rejects_bad_channel(self):
        self.escribir({"channel": 20, "actions": {"go": {"type": "note", "number": 40}}})
        with self.assertRaises(ValueError):
            load_mapping(self.path)

    def test_rejects_bad_action(self):
        self.escribir({"actions": {"go": {"type": "button", "number": 1}}})
        with self.assertRaises(ValueError):
            load_mapping(self.path)

    def test_resolve_missing_action_lists_available(self):
        self.escribir({"actions": {"go": {"type": "note", "number": 40}}})
        mapping = load_mapping(self.path)
        with self.assertRaises(KeyError) as ctx:
            resolve(mapping, "blackout")
        self.assertIn("Mapeadas: go", str(ctx.exception))

    def test_write_example(self):
        write_example(self.path)
        mapping = load_mapping(self.path)
        self.assertIn("group_1", mapping["actions"])


class TestBridge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "mapping.json"
        path.write_text(
            json.dumps(
                {
                    "channel": 0,
                    "actions": {
                        "group_3": {"type": "note", "number": 38},
                        "dimmer": {"type": "cc", "control": 1},
                        "go": {"type": "note", "number": 40},
                    },
                }
            ),
            encoding="utf-8",
        )
        self.bridge = WolfmixBridge.from_file(path)

    def tearDown(self):
        self.bridge.close()
        self._tmp.cleanup()

    def test_group_and_go(self):
        self.assertEqual(self.bridge.group(3), 0x902664)
        self.assertEqual(self.bridge.go(), 0x90287F)
        self.assertEqual(len(self.bridge.log()), 2)

    def test_dimmer_maps_percent(self):
        self.assertEqual(self.bridge.dimmer(100), 0xB0017F)
        self.assertEqual(self.bridge.dimmer(0), 0xB00100)

    def test_dimmer_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            self.bridge.dimmer(101)

    def test_group_range(self):
        with self.assertRaises(ValueError):
            self.bridge.group(9)

    def test_unmapped_action_raises(self):
        with self.assertRaises(KeyError):
            self.bridge.blackout()

    def test_dry_run_never_opens_device(self):
        self.assertFalse(self.bridge.live)
        self.assertTrue(self.bridge.midi.dry_run)


if __name__ == "__main__":
    unittest.main()
