"""Tests del codec OSC: framing exacto, roundtrip y dry-run."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.osc_codec import decode_message, encode_message, osc_pad, send_message  # noqa: E402


class TestPadding(unittest.TestCase):
    def test_pad_to_multiple_of_four(self):
        self.assertEqual(osc_pad(b"abc"), b"abc\x00")
        self.assertEqual(osc_pad(b"abcd"), b"abcd")
        self.assertEqual(len(osc_pad(b"/gma3/cmd")), 12)
        self.assertTrue(all(len(osc_pad(bytes(n))) % 4 == 0 for n in range(1, 20)))


class TestFraming(unittest.TestCase):
    def test_contract_packet_is_60_bytes(self):
        """Vector del contrato: 12 (address) + 4 (tag) + 44 (arg)."""
        payload = encode_message("/gma3/cmd", ['Set Fixture 11 Attribute "PAN" At -157.38'])
        expected = (
            b"/gma3/cmd".ljust(12, b"\x00")
            + b",s".ljust(4, b"\x00")
            + b'Set Fixture 11 Attribute "PAN" At -157.38\x00'.ljust(44, b"\x00")
        )
        self.assertEqual(len(payload), 60)
        self.assertEqual(payload, expected)

    def test_no_args_has_empty_type_tag(self):
        self.assertEqual(encode_message("/gma3/ping"), b"/gma3/ping\x00\x00," + b"\x00\x00\x00")

    def test_rejects_relative_or_dirty_address(self):
        for bad in ("gma3/cmd", "", "/gma3/cmd\n", "/gma3 cmd"):
            with self.assertRaises(ValueError):
                encode_message(bad, [])


class TestDecode(unittest.TestCase):
    def test_roundtrip_mixed_types(self):
        payload = encode_message("/mcp/state", ["EVENT|x", 42, 1.5])
        decoded = decode_message(payload)
        self.assertEqual(decoded["address"], "/mcp/state")
        self.assertEqual(decoded["type_tags"], ",sif")
        self.assertEqual(decoded["args"][0], "EVENT|x")
        self.assertEqual(decoded["args"][1], 42)
        self.assertAlmostEqual(decoded["args"][2], 1.5, places=5)

    def test_rejects_misaligned_packet(self):
        with self.assertRaises(ValueError):
            decode_message(b"/gma3\x00\x00abc")

    def test_rejects_unknown_type_tag(self):
        with self.assertRaises(ValueError):
            decode_message(b"/x\x00\x00,h\x00\x00\x00\x00")


class TestSend(unittest.TestCase):
    def test_dry_run_never_opens_socket(self):
        info = send_message("127.0.0.1", 8000, "/gma3/cmd", ["Clear"], dry_run=True)
        self.assertTrue(info["dry_run"])
        self.assertFalse(info["sent"])
        self.assertEqual(info["bytes"] % 4, 0)
        self.assertEqual(len(info["hex"]), info["bytes"] * 2)

    def test_invalid_port(self):
        with self.assertRaises(ValueError):
            send_message("127.0.0.1", 0, "/gma3/cmd", ["Clear"], dry_run=True)


if __name__ == "__main__":
    unittest.main()
