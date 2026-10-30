"""Tests del servidor MCP: protocolo, seguridad y dry-run."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.server import PROTOCOL_VERSION, handle_message  # noqa: E402
from mcp_server.tools import list_tools  # noqa: E402


def rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


SHOW = {
    "schema_version": "1.0.0",
    "source": {"system": "grandMA3", "extracted_at": "2026-10-30T14:00:00Z"},
    "fixtures": [{
        "id": "11", "name": "Beam_1",
        "type": {"manufacturer": "Robe", "model": "Pointe"},
        "patch": {"universe": 3, "address": 1},
        "position": {"x": -3.0, "y": 0.0, "z": 4.0, "mount_type": "truss"},
        "semantic": {"bearing_deg": None, "calculated_pan": None, "pan_offset_deg": 0.0},
    }],
}


def call(name: str, arguments: dict) -> dict:
    return handle_message(rpc("tools/call", {"name": name, "arguments": arguments}))


def unwrap(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


class TestProtocol(unittest.TestCase):
    def test_initialize(self):
        response = handle_message(rpc("initialize", {"protocolVersion": "2024-11-05"}))
        self.assertEqual(response["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(response["result"]["serverInfo"]["name"], "showpatch")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_tools_list(self):
        response = handle_message(rpc("tools/list"))
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("show.translate", names)
        self.assertIn("osc.send", names)
        self.assertGreaterEqual(len(names), 10)
        self.assertEqual(len(names), len(set(names)))

    def test_notification_returns_none(self):
        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method(self):
        response = handle_message(rpc("does/not/exist"))
        self.assertEqual(response["error"]["code"], -32601)

    def test_bad_envelope(self):
        self.assertEqual(handle_message(rpc("ping") | {"jsonrpc": "1.0"})["error"]["code"], -32600)
        self.assertEqual(handle_message({"jsonrpc": "2.0", "id": 1})["error"]["code"], -32600)

    def test_ping(self):
        self.assertEqual(handle_message(rpc("ping"))["result"], {})


class TestTools(unittest.TestCase):
    def test_translate_matches_contract(self):
        envelope = unwrap(call("show.translate", {"show": SHOW, "target": "grandMA3"}))
        self.assertTrue(envelope["ok"])
        commands = envelope["result"]["commands"]
        self.assertIn('Patch Fixture 11 At 3.1', commands)
        self.assertIn('Label Fixture 11 "Beam_1"', commands)

    def test_validate_detects_bad_patch(self):
        broken = json.loads(json.dumps(SHOW))
        broken["fixtures"][0]["patch"]["address"] = 900
        envelope = unwrap(call("show.validate", {"show": broken, "post_parser": False}))
        self.assertFalse(envelope["result"]["valid"])

    def test_parse_ma3_from_repo_fixture(self):
        envelope = unwrap(call("show.parse_ma3", {"path": "tests/fixtures/ma3_export_sample.xml"}))
        self.assertTrue(envelope["result"]["valid"])
        self.assertGreaterEqual(len(envelope["result"]["show"]["fixtures"]), 3)

    def test_horseshoe_writes_semantics(self):
        show = json.loads(json.dumps(SHOW))
        second = json.loads(json.dumps(SHOW["fixtures"][0]))
        second["id"] = "12"
        second["name"] = "Beam_2"
        second["position"] = {"x": 3.0, "y": 0.0, "z": 4.0, "mount_type": "truss"}
        show["fixtures"].append(second)

        envelope = unwrap(call("layout.horseshoe", {"show": show, "radius": 4.0}))
        fixture = envelope["result"]["show"]["fixtures"][0]
        self.assertIsNotNone(fixture["semantic"]["bearing_deg"])
        self.assertIsNotNone(fixture["semantic"]["calculated_pan"])

    def test_fingerprint_requires_frames(self):
        response = call("fixture.fingerprint", {})
        self.assertEqual(response["error"]["code"], -32602)

    def test_unknown_tool(self):
        self.assertEqual(call("nope.nope", {})["error"]["code"], -32601)

    def test_path_traversal_rejected(self):
        response = call("show.parse_ma3", {"path": "../../README.md"})
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("fuera del workspace", response["error"]["message"])


class TestOscSafety(unittest.TestCase):
    def test_dry_run_by_default(self):
        envelope = unwrap(call("osc.send", {"ip": "127.0.0.1", "address": "/gma3/cmd", "args": ["Clear"]}))
        result = envelope["result"]
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["sent"])
        self.assertEqual(result["bytes"] % 4, 0)
        self.assertEqual(len(result["hex"]), result["bytes"] * 2)

    def test_rejects_dmx_address(self):
        response = call("osc.send", {"ip": "127.0.0.1", "address": "/dmx/universe/1"})
        self.assertEqual(response["error"]["code"], -32602)

    def test_accepts_configurable_ma3_prefix(self):
        """El prefijo OSC de MA3 se configura; G3Link usa `grandMA3` y puerto 8081."""
        envelope = unwrap(
            call("osc.send", {"ip": "127.0.0.1", "port": 8081, "address": "/grandMA3/cmd", "args": ["Clear"]})
        )
        self.assertTrue(envelope["result"]["dry_run"])
        self.assertEqual(envelope["result"]["bytes"] % 4, 0)

    def test_verb_allowlist_applies_to_both_prefixes(self):
        for prefix in ("/gma3/", "/grandMA3/"):
            response = call("osc.send", {"ip": "127.0.0.1", "address": prefix + "cmd", "args": ["rm -rf /"]})
            self.assertEqual(response["error"]["code"], -32602)

    def test_rejects_unknown_ma3_verb(self):
        response = call("osc.send", {"ip": "127.0.0.1", "address": "/gma3/cmd", "args": ["rm -rf /"]})
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("Verbo MA3 no permitido", response["error"]["message"])

    def test_rejects_non_scalar_args(self):
        response = call("osc.send", {"ip": "127.0.0.1", "address": "/gma3/cmd", "args": [{"a": 1}]})
        self.assertEqual(response["error"]["code"], -32602)


class TestLuaGeneration(unittest.TestCase):
    def test_generates_escaped_script_inside_generated_dir(self):
        show = json.loads(json.dumps(SHOW))
        show["fixtures"][0]["name"] = 'Beam "A" \\ 1'
        response = call("lua.generate", {"show": show, "macro_name": "test_macro_unit"})
        envelope = unwrap(response)
        script = envelope["result"]["script"]
        path = ROOT / envelope["result"]["path"]
        try:
            self.assertTrue(path.exists())
            self.assertIn("return function()", script)
            self.assertIn('gma.cmd("', script)
            self.assertIn('\\"', script)
            self.assertTrue(str(path).startswith(str(ROOT / "generated")))
        finally:
            path.unlink(missing_ok=True)
            if path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()

    def test_rejects_unsafe_macro_name(self):
        response = call("lua.generate", {"show": SHOW, "macro_name": "../evil"})
        self.assertEqual(response["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
