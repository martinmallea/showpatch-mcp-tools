"""App local de ShowPatch: panel, buscador de fixtures y calculadoras.

Servidor HTTP con la librería estándar, sin dependencias. La app corre en el
mismo sitio que el show: no hay nube de por medio y no se abre al mundo salvo
que se pida explícitamente y con token.

    python bridge.py web                # http://127.0.0.1:8787
    python bridge.py web --port 9000
    python bridge.py web --host 0.0.0.0 --token secreto   # red de show

Seguridad:
- Por defecto escucha sólo en loopback.
- Si se expone en red, exige token: sin token no arranca.
- No hay CORS abierto ni DMX crudo: la API devuelve cálculos y búsquedas.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import fixture_library  # noqa: E402
from core.color_calc import convert  # noqa: E402
from core.colorblind import MODES, confusable_pairs, name_color, simulate_all  # noqa: E402
from core.dmx_calc import (  # noqa: E402
    UNIVERSE_SIZE,
    address_range,
    capacity,
    dip_switches,
    next_free,
    universe_of,
)

STATIC = Path(__file__).resolve().parent / "static"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

_MONITOR = None


def get_monitor():
    """Monitor DMX compartido. Arranca los listeners la primera vez."""
    global _MONITOR
    if _MONITOR is None:
        from core.dmx_monitor import DmxMonitor, start_listeners

        _MONITOR = DmxMonitor()
        start_listeners(_MONITOR)
    return _MONITOR


def dmx_live_payload(full: bool = False) -> dict:
    return get_monitor().snapshot(full=full)


_CAPTURE = None


def dmx_capture_payload(action: str, name: str = "") -> dict:
    """Captura a disco: pasivo, sin emitir nada. Un fichero por sesión."""
    global _CAPTURE
    from core.dmx_capture import new_capture

    monitor = get_monitor()
    if action == "start":
        if _CAPTURE is not None:
            raise ValueError("Ya hay una captura en curso")
        _CAPTURE = new_capture(ROOT / "captures", name or "captura")
        monitor.set_sink(_CAPTURE.write)
        return {"capturing": True, "path": str(_CAPTURE.path.relative_to(ROOT))}
    if action == "stop":
        if _CAPTURE is None:
            return {"capturing": False, "summary": None}
        monitor.set_sink(None)
        info = _CAPTURE.close()
        _CAPTURE = None
        return {"capturing": False, "summary": info}
    raise ValueError("Acción inválida: usa start o stop")


def dmx_record_payload(action: str) -> dict:
    monitor = get_monitor()
    if action == "start":
        monitor.record_start()
    elif action == "stop":
        return {"stopped": monitor.record_stop(), "recording": monitor.recording()}
    else:
        raise ValueError("Acción inválida: usa start o stop")
    return {"recording": monitor.recording()}


def fixtures_payload(query: str = "", manufacturer: str = "", limit: int = 50) -> dict:
    """Busca en el índice local (14k+ fixtures). Sin red, sin API externa."""
    limit = max(1, min(int(limit or 50), 200))
    rows = fixture_library.search(manufacturer or None, query or None, limit=limit)
    info = fixture_library.summary()
    return {
        "count": len(rows),
        "indexed": info.get("count", 0),
        "library_version": info.get("library_version"),
        "synced_at": info.get("synced_at"),
        "results": rows,
    }


def _overlaps(ranges: list[tuple[int, int]]) -> list[dict]:
    ordered = sorted((int(start), int(end)) for start, end in ranges)
    found = []
    for index in range(len(ordered) - 1):
        start_a, end_a = ordered[index]
        start_b, end_b = ordered[index + 1]
        if start_b <= end_a:
            found.append(
                {
                    "a": [start_a, end_a],
                    "b": [start_b, end_b],
                    "overlap": [start_b, min(end_a, end_b)],
                }
            )
    return found


def dmx_payload(data: dict) -> dict:
    """Rango, DIP switches, capacidad y hueco libre para un parche concreto."""
    address = int(data.get("address", 1))
    footprint = int(data.get("footprint", 1))
    start, end = address_range(address, footprint)

    occupied_raw = data.get("occupied") or []
    occupied: list[tuple[int, int]] = []
    for pair in occupied_raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("Cada rango ocupado debe ser [inicio, fin]")
        first, last = int(pair[0]), int(pair[1])
        if first > last:
            first, last = last, first
        if not (1 <= first <= UNIVERSE_SIZE and 1 <= last <= UNIVERSE_SIZE):
            raise ValueError(f"Rango fuera de 1..{UNIVERSE_SIZE}: {pair}")
        occupied.append((first, last))

    return {
        "range": [start, end],
        "universe": int(data.get("universe", universe_of(address))),
        "dip_switches": dip_switches(address),
        "capacity": capacity(footprint),
        "footprint": footprint,
        "next_free": next_free(occupied, footprint),
        "occupied": occupied,
        "overlaps": _overlaps(occupied + [(start, end)]),
        "usage_percent": round(footprint / UNIVERSE_SIZE * 100, 1),
    }


def color_payload(data: dict) -> dict:
    """Convierte un color y simula cómo se ve con cada dicromacia."""
    if "palette" in data:
        colors = [convert({"hex": value} if isinstance(value, str) else {"rgb": value})["rgb"] for value in data["palette"]]
        return {
            "palette": colors,
            "names": [name_color(color) for color in colors],
            "confusable": {mode: confusable_pairs(colors, mode) for mode in MODES},
            "simulated": {mode: [simulate_all(color)[mode] for color in colors] for mode in MODES},
        }

    if "hex" in data:
        info = convert({"hex": data["hex"]})
    else:
        info = convert({"rgb": data.get("rgb", [0, 0, 0])})
    info["name"] = name_color(info["rgb"])
    info["simulated"] = simulate_all(info["rgb"])
    info["simulated_names"] = {mode: name_color(value) for mode, value in info["simulated"].items()}
    return info


def status_payload() -> dict:
    """Resumen del plan, para que el panel no sea sólo una calculadora."""
    plan_path = ROOT / "orchestration" / "work_packages.json"
    state_path = ROOT / "orchestration" / "state.json"
    total = 0
    if plan_path.is_file():
        total = len(json.loads(plan_path.read_text(encoding="utf-8")).get("work_packages", []))
    done = 0
    updated = None
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        done = sum(1 for item in state.get("work_packages", {}).values() if item.get("status") == "done")
        updated = state.get("updated_at")
    info = fixture_library.summary()
    return {
        "work_packages": {"done": done, "total": total, "updated_at": updated},
        "fixtures": {"indexed": info.get("count", 0), "library_version": info.get("library_version")},
    }


def make_handler(bind: dict):
    token = bind.get("token")
    index_file = STATIC / "index.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShowPatch/1.3"

        def log_message(self, fmt, *args):  # silencio: no ensuciar la consola
            return

        def _authorized(self, query: dict) -> bool:
            if not token:
                return True
            provided = self.headers.get("X-ShowPatch-Token") or (query.get("token", [""])[0])
            return provided == token

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status: int = 200) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self._json({"error": message}, status)

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if not self._authorized(query):
                return self._error(401, "Token requerido")
            if parts.path in ("/", "/index.html"):
                if not index_file.is_file():
                    return self._error(500, "Falta web/static/index.html")
                return self._send(200, index_file.read_bytes(), "text/html; charset=utf-8")
            if parts.path == "/api/fixtures":
                return self._json(
                    fixtures_payload(
                        query.get("q", [""])[0],
                        query.get("manufacturer", [""])[0],
                        int(query.get("limit", ["50"])[0] or 50),
                    )
                )
            if parts.path == "/api/dmx/live":
                return self._json(dmx_live_payload(full=bool(query.get("full", [""])[0])))
            if parts.path == "/api/status":
                return self._json(status_payload())
            return self._error(404, "Ruta no encontrada")

        def do_POST(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            if not self._authorized(parse_qs(parts.query)):
                return self._error(401, "Token requerido")
            length = int(self.headers.get("Content-Length") or 0)
            if length > 200_000:
                return self._error(413, "Cuerpo demasiado grande")
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._error(400, "JSON inválido")
            if not isinstance(data, dict):
                return self._error(400, "Se esperaba un objeto JSON")
            try:
                if parts.path == "/api/dmx":
                    return self._json(dmx_payload(data))
                if parts.path == "/api/color":
                    return self._json(color_payload(data))
                if parts.path == "/api/dmx/capture":
                    return self._json(dmx_capture_payload(str(data.get("action", "")), str(data.get("name", ""))))
                if parts.path == "/api/dmx/record":
                    return self._json(dmx_record_payload(str(data.get("action", ""))))
            except (ValueError, TypeError) as exc:
                return self._error(400, str(exc))
            return self._error(404, "Ruta no encontrada")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787, token: str | None = None, open_browser: bool = True) -> int:
    if host not in LOOPBACK and not token:
        raise SystemExit("Exponer la app en red exige --token. Un panel de control abierto en el Wi-Fi del recinto es un blackout esperando.")

    server = ThreadingHTTPServer((host, port), make_handler({"token": token}))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"ShowPatch en {url}")
    if token:
        print("Token requerido: cabecera X-ShowPatch-Token o ?token=")
    print("Ctrl+C para parar.")
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
    parser = argparse.ArgumentParser(description="App local de ShowPatch")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    return serve(args.host, args.port, args.token, not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
