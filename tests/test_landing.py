"""Tests de la landing: registro, duplicados y entrega de descargas."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from landing.server import make_handler, record_signup  # noqa: E402


class SignupFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "signups.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def lines(self):
        return [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()] if self.path.exists() else []

    def test_valid_signup_writes_record(self):
        ok, _ = record_signup({"email": "Tecnico@Show.com", "role": "Operador", "rig": "grandMA3", "pc_ack": True}, self.path)
        self.assertTrue(ok)
        entry = json.loads(self.lines()[0])
        self.assertEqual(entry["email"], "tecnico@show.com")
        self.assertTrue(entry["pc_ack"])

    def test_invalid_email_rejected(self):
        for bad in ("", "sin-arroba", "a@b", "a b@c.com"):
            ok, _ = record_signup({"email": bad}, self.path)
            self.assertFalse(ok, bad)
        self.assertEqual(self.lines(), [])

    def test_duplicate_does_not_duplicate(self):
        record_signup({"email": "uno@show.com"}, self.path)
        record_signup({"email": "UNO@show.com"}, self.path)
        self.assertEqual(len(self.lines()), 1)

    def test_survives_corrupt_line(self):
        self.path.write_text("basura\n", encoding="utf-8")
        ok, _ = record_signup({"email": "dos@show.com"}, self.path)
        self.assertTrue(ok)
        self.assertEqual(len(self.lines()), 2)


class ServerCase(unittest.TestCase):
    bind_overrides: dict = {}

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.signups = base / "signups.jsonl"
        cls.html_source = base / "ui.html"
        cls.html_source.write_text("<html><body>SHOWPATCH UI</body></html>", encoding="utf-8")
        bind = {
            "github": "https://github.com/ejemplo/showpatch",
            "github_note": "público en preparación",
            "app": "http://127.0.0.1:8787/",
            "html_source": cls.html_source,
            "signups": cls.signups,
            "zip": None,
        }
        bind.update(cls.bind_overrides)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bind))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.headers, response.read()

    def post(self, path, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())


class TestLanding(ServerCase):
    def test_index_served(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"SHOWPATCH", body)

    def test_config(self):
        status, _, body = self.get("/api/config")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["version"], "1.6.0")
        self.assertFalse(data["has_binary"])

    def test_signup_returns_links(self):
        status, data = self.post("/api/signup", {"email": "beta@show.com", "rig": "Wolfmix", "pc_ack": True})
        self.assertEqual(status, 200)
        self.assertIn("windows", data["downloads"])
        self.assertIn("html", data["downloads"])
        self.assertEqual(data["downloads"]["github"], "https://github.com/ejemplo/showpatch")

    def test_bad_email_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/signup", {"email": "nope"})
        self.assertEqual(ctx.exception.code, 400)

    def test_html_download_is_attachment(self):
        status, headers, body = self.get("/download/html")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertIn(b"SHOWPATCH UI", body)

    def test_windows_without_binary_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/download/windows")
        self.assertEqual(ctx.exception.code, 404)


class TestLandingWithBinary(ServerCase):
    bind_overrides = {"zip": Path(__file__)}

    def test_windows_download_serves_zip(self):
        status, headers, body = self.get("/download/windows")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertGreater(len(body), 100)


if __name__ == "__main__":
    unittest.main()
