"""Tests de la app local: payloads puros y servidor HTTP real."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.app import color_payload, dmx_payload, fixtures_payload, make_handler, status_payload  # noqa: E402


class TestFixturesPayload(unittest.TestCase):
    def test_search_returns_channels(self):
        data = fixtures_payload("pointe", "robe", 10)
        if data["indexed"] == 0:
            self.skipTest("índice no generado")
        self.assertGreater(len(data["results"]), 0)
        row = data["results"][0]
        self.assertIn("channels", row)
        self.assertIn("manufacturer", row)
        self.assertLessEqual(len(data["results"]), 10)

    def test_limit_is_bounded(self):
        self.assertLessEqual(len(fixtures_payload("", "", 999)["results"]), 200)

    def test_unknown_query_is_empty_not_error(self):
        self.assertEqual(fixtures_payload("zzzz-no-existe", "zzzz", 5)["results"], [])


class TestDmxPayload(unittest.TestCase):
    def test_basic(self):
        data = dmx_payload({"address": 1, "footprint": 31})
        self.assertEqual(data["range"], [1, 31])
        self.assertEqual(data["dip_switches"], [1])
        self.assertEqual(data["capacity"], 16)

    def test_next_free_and_overlap(self):
        data = dmx_payload({"address": 10, "footprint": 10, "occupied": [[1, 15]]})
        self.assertEqual(data["next_free"], 16)
        self.assertEqual(len(data["overlaps"]), 1)
        self.assertEqual(data["overlaps"][0]["overlap"], [10, 15])

    def test_out_of_universe_raises(self):
        with self.assertRaises(ValueError):
            dmx_payload({"address": 500, "footprint": 40})

    def test_bad_occupied(self):
        with self.assertRaises(ValueError):
            dmx_payload({"address": 1, "footprint": 1, "occupied": ["1-10"]})


class TestColorPayload(unittest.TestCase):
    def test_single_color(self):
        data = color_payload({"rgb": [255, 0, 0]})
        self.assertEqual(data["hex"], "#ff0000")
        self.assertEqual(data["name"], "rojo")
        self.assertEqual(data["cmy"][1], 100.0)
        self.assertEqual(set(data["simulated"]), {"protanopia", "deuteranopia", "tritanopia"})

    def test_hex_input(self):
        self.assertEqual(color_payload({"hex": "#00ff00"})["rgb"], [0, 255, 0])

    def test_palette_conflicts(self):
        data = color_payload({"palette": ["#a000a0", "#808080"]})
        self.assertEqual(len(data["palette"]), 2)
        self.assertTrue(data["confusable"]["deuteranopia"])


class TestStatus(unittest.TestCase):
    def test_status_shape(self):
        data = status_payload()
        self.assertIn("work_packages", data)
        self.assertIn("fixtures", data)
        self.assertGreaterEqual(data["work_packages"]["total"], 1)


class ServerCase(unittest.TestCase):
    token = None

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler({"token": cls.token}))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.read()

    def post(self, path, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())


class TestServer(ServerCase):
    def test_index_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"SHOWPATCH", body)

    def test_api_fixtures(self):
        status, body = self.get("/api/fixtures?q=pointe&limit=5")
        self.assertEqual(status, 200)
        self.assertIn("results", json.loads(body))

    def test_api_color(self):
        status, data = self.post("/api/color", {"rgb": [0, 0, 255]})
        self.assertEqual(status, 200)
        self.assertEqual(data["name"], "azul")

    def test_api_dmx_error_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dmx", {"address": 600, "footprint": 1})
        self.assertEqual(ctx.exception.code, 400)

    def test_unknown_route_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nada")
        self.assertEqual(ctx.exception.code, 404)


class TestServerWithToken(ServerCase):
    token = "secreto"

    def test_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/status")
        self.assertEqual(ctx.exception.code, 401)

    def test_accepts_query_token(self):
        status, body = self.get("/api/status?token=secreto")
        self.assertEqual(status, 200)
        self.assertIn(b"work_packages", body)


if __name__ == "__main__":
    unittest.main()
