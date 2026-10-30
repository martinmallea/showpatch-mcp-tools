"""Landing de ShowPatch con registro y entrega de descargas.

Sirve la página, guarda los correos en JSONL y entrega los enlaces sólo después
del registro. Sin dependencias y sin servicios de terceros: lo que entra se queda
en tu disco.

    python bridge.py landing --port 8790

Qué se entrega tras el registro:
- El ZIP de Windows (si existe en el workspace).
- El HTML completo de la interfaz, sin minificar.
- El enlace al repositorio (marcado como "en preparación" hasta que exista).

Privacidad: se guarda correo, rol, consola y si aceptó el aviso de PC. No se
guarda IP ni user-agent. Se puede borrar el fichero y no queda rastro.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
LANDING = Path(__file__).resolve().parent
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

DEFAULT_SIGNS = LANDING / "data" / "signups.jsonl"


def find_zip() -> Path | None:
    """Busca el ZIP más reciente junto al repo (el entregable de la beta)."""
    candidates = sorted(ROOT.parent.glob("showpatch-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


CONFIG_FILE = LANDING / "config.json"
DEFAULTS = {
    "version": "1.9.1",
    "github": "https://github.com/tuusuario/showpatch",
    "github_note": "público en preparación",
    "app": "http://127.0.0.1:8787/",
    "zip": None,
}


def config() -> dict:
    """Configuración de la landing: valores por defecto + landing/config.json.

    Publicar no debe exigir tocar Python: la URL del repo y el ZIP se cambian en
    el JSON. Si `zip` es null se autodetecta el ZIP más reciente junto al repo.
    """
    data = dict(DEFAULTS)
    if CONFIG_FILE.is_file():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update({key: value for key, value in loaded.items() if value is not None})
        except json.JSONDecodeError:
            pass

    candidate = Path(str(data["zip"])) if data.get("zip") else find_zip()
    resolved = candidate if candidate and Path(candidate).is_file() else None

    return {
        "version": data.get("version", DEFAULTS["version"]),
        "github": data.get("github", DEFAULTS["github"]),
        "github_note": data.get("github_note", DEFAULTS["github_note"]),
        "app": data.get("app", DEFAULTS["app"]),
        "html_source": ROOT / "web" / "static" / "panel.html",
        "signups": DEFAULT_SIGNS,
        "zip": resolved,
    }


def record_signup(data: dict, path: Path) -> tuple[bool, str]:
    """Valida y guarda. Devuelve (ok, mensaje). Un correo repetido no duplica."""
    email = (data.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return False, "Ese correo no parece válido."

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(json.loads(line).get("email"))
            except json.JSONDecodeError:
                continue

    if email not in existing:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "email": email,
            "role": (data.get("role") or "")[:40],
            "rig": (data.get("rig") or "")[:40],
            "pc_ack": bool(data.get("pc_ack")),
        }
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True, "ok"


def read_signups(path: str | Path) -> list[dict]:
    """Lee los registros; una línea corrupta no invalida el resto."""
    target = Path(path)
    if not target.is_file():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def admin_payload(bind: dict) -> dict:
    """Todo junto: registros, estado del plan, capturas y enlaces."""
    rows = read_signups(bind.get("signups"))
    total = 0
    done = 0
    plan_path = ROOT / "orchestration" / "work_packages.json"
    state_path = ROOT / "orchestration" / "state.json"
    try:
        total = len(json.loads(plan_path.read_text(encoding="utf-8")).get("work_packages", []))
    except (OSError, json.JSONDecodeError):
        pass
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        done = sum(1 for item in state.get("work_packages", {}).values() if item.get("status") == "done")
    except (OSError, json.JSONDecodeError):
        pass

    captures = []
    try:
        from core.dmx_capture import list_captures

        captures = list_captures(ROOT / "captures")
    except (ImportError, OSError):
        pass

    zip_path = bind.get("zip")
    return {
        "version": bind.get("version"),
        "github": bind.get("github"),
        "app": bind.get("app"),
        "signups": {"count": len(rows), "rows": rows[-50:]},
        "captures": captures,
        "project": {"done": done, "total": total},
        "zip": {"path": str(zip_path), "kb": round(Path(zip_path).stat().st_size / 1024)} if zip_path else None,
    }


def downloads(bind: dict) -> dict:
    zip_path = bind.get("zip")
    return {
        "windows": "/download/windows" if zip_path else "/download/windows",
        "html": "/download/html",
        "app": bind.get("app", "http://127.0.0.1:8787/"),
        "github": bind.get("github", "#"),
    }


def make_handler(bind: dict):
    index_file = LANDING / "index.html"
    admin_file = LANDING / "admin.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShowPatchLanding/1.0"

        def log_message(self, fmt, *args):
            return

        def _send(self, status: int, body: bytes, ctype: str, *, filename: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status: int = 200) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path in ("/admin", "/api/admin"):
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._json({"error": "Sólo desde esta máquina"}, 403)
                if path == "/api/admin":
                    return self._json(admin_payload(bind))
                if not admin_file.is_file():
                    return self._json({"error": "Falta landing/admin.html"}, 500)
                return self._send(200, admin_file.read_bytes(), "text/html; charset=utf-8")

            if path in ("/", "/index.html"):
                if not index_file.is_file():
                    return self._json({"error": "Falta landing/index.html"}, 500)
                return self._send(200, index_file.read_bytes(), "text/html; charset=utf-8")

            if path == "/api/config":
                return self._json(
                    {
                        "version": bind.get("version", DEFAULTS["version"]),
                        "github": bind.get("github"),
                        "github_note": bind.get("github_note"),
                        "has_binary": bool(bind.get("zip")),
                    }
                )

            if path == "/download/html":
                source = Path(bind.get("html_source") or "")
                if not source.is_file():
                    return self._json({"error": "El HTML de la app no está disponible."}, 404)
                return self._send(
                    200, source.read_bytes(), "text/html; charset=utf-8", filename="showpatch-ui.html"
                )

            if path == "/download/windows":
                zip_path = bind.get("zip")
                if not zip_path or not Path(zip_path).is_file():
                    return self._json(
                        {"error": "La beta aún no tiene binario publicado. Te aviso por correo."}, 404
                    )
                return self._send(
                    200, Path(zip_path).read_bytes(), "application/zip", filename=Path(zip_path).name
                )

            return self._json({"error": "Ruta no encontrada"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path != "/api/signup":
                return self._json({"error": "Ruta no encontrada"}, 404)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 20_000:
                return self._json({"error": "Cuerpo demasiado grande"}, 413)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "JSON inválido"}, 400)
            if not isinstance(data, dict):
                return self._json({"error": "Se esperaba un objeto JSON"}, 400)

            ok, message = record_signup(data, Path(bind["signups"]))
            if not ok:
                return self._json({"error": message}, 400)
            return self._json(
                {
                    "ok": True,
                    "downloads": downloads(bind),
                    "github_note": bind.get("github_note"),
                    "message": "Guarda los enlaces: no se vuelven a enviar.",
                }
            )

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8790, open_browser: bool = True) -> int:
    bind = config()
    if host not in LOOPBACK:
        print("Aviso: estás sirviendo la landing fuera de loopback. Para producción usa un host real.", file=sys.stderr)
    server = ThreadingHTTPServer((host, port), make_handler(bind))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"Landing en {url}")
    print(f"Registros: {bind['signups']}")
    print(f"Binario: {bind['zip'] or 'no publicado todavía'}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Landing de ShowPatch")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    return serve(args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
