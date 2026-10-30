"""Grabadora de comandos y reproductor con autoplay.

Qué graba y qué no, porque la diferencia importa:

- Graba **mensajes de consola**: dirección OSC + argumentos + instante. Es lo que
  el puente envía de verdad.
- **No graba DMX.** El puente no emite DMX a propósito: manda comandos y la
  consola renderiza. Grabar tramas DMX sería otro producto (y otro modelo de
  seguridad).

Con eso se puede repetir una sesión de enfoque, un pase de cues o una secuencia
de ajustes sin reescribirla, con velocidad y bucle.

Formato: JSONL, una línea por evento. Legible con `type` y robusto si se corta la
luz a mitad de grabación.

    {"v":1,"kind":"meta","name":"take1","created_at":"...","console":"grandMA3"}
    {"v":1,"kind":"event","t":0.0,"address":"/gma3/cmd","args":["Go Sequence 1"]}
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from core.osc_codec import send_message

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "recordings"
NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def slugify(name: str) -> str:
    cleaned = NAME_RE.sub("-", (name or "").strip()).strip("-")
    return cleaned[:48] or "take"


def new_recording(name: str, directory: str | Path | None = None, *, console: str = "grandMA3") -> Path:
    """Crea el fichero con su cabecera y devuelve la ruta."""
    target_dir = Path(directory) if directory else DEFAULT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = target_dir / f"{stamp}_{slugify(name)}.jsonl"
    header = {
        "v": 1,
        "kind": "meta",
        "name": name,
        "console": console,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


class Recorder:
    """Acumula eventos con marca de tiempo relativa (monotónica, no de reloj)."""

    def __init__(self, path: str | Path, *, reset: bool = False):
        self.path = Path(path)
        if reset:
            header = {"v": 1, "kind": "meta", "name": self.path.stem,
                      "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self.path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        self._start = time.monotonic()
        self.count = 0

    def append(self, address: str, args=(), *, at: float | None = None) -> dict:
        event = {
            "v": 1,
            "kind": "event",
            "t": round(at if at is not None else time.monotonic() - self._start, 3),
            "address": address,
            "args": list(args),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.count += 1
        return event


def load(path: str | Path) -> dict:
    """Lee una grabación; ignora líneas corruptas en lugar de fallar entera."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"No existe la grabación: {target}")
    meta: dict = {}
    events: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") == "meta":
            meta = row
        elif row.get("kind") == "event" and isinstance(row.get("address"), str):
            events.append(row)
    events.sort(key=lambda item: float(item.get("t", 0.0)))
    return {"meta": meta, "events": events, "duration": events[-1]["t"] if events else 0.0}


def plan(events: list[dict], *, speed: float = 1.0, loops: int = 1, gap: float = 0.25) -> list[dict]:
    """Calcula el calendario de reproducción sin dormir ni enviar nada.

    Separar el cálculo del envío es lo que hace testeable un reproductor: se puede
    comprobar la aritmética de tiempos y de bucles sin esperar en tiempo real.
    """
    if speed <= 0:
        raise ValueError("La velocidad debe ser mayor que 0")
    if loops < 1:
        raise ValueError("Los bucles deben ser al menos 1")
    if not events:
        return []

    base = float(events[0].get("t", 0.0))
    schedule: list[dict] = []
    offset = 0.0
    span = 0.0
    for loop_index in range(loops):
        for event in events:
            relative = (float(event.get("t", 0.0)) - base) / speed
            schedule.append(
                {
                    "at": round(offset + relative, 3),
                    "loop": loop_index,
                    "address": event["address"],
                    "args": list(event.get("args") or []),
                }
            )
            span = max(span, relative)
        offset += span + gap
        span = 0.0
    return schedule


def replay(
    record: dict,
    *,
    ip: str = "127.0.0.1",
    port: int = 8000,
    speed: float = 1.0,
    loops: int = 1,
    live: bool = False,
    sleep=time.sleep,
    sender=None,
) -> dict:
    """Reproduce la grabación. En seco por defecto: ``live=False`` no abre socket."""
    schedule = plan(record.get("events", []), speed=speed, loops=loops)
    if not schedule:
        return {"sent": 0, "live": live, "duration": 0.0, "results": []}

    results = []
    started = 0.0
    for item in schedule:
        wait = item["at"] - started
        if wait > 0:
            sleep(wait)
        started = item["at"]
        if sender is not None:
            result = sender(item["address"], item["args"])
        else:
            result = send_message(ip, port, item["address"], item["args"], dry_run=not live)
        results.append({"at": item["at"], "address": item["address"], "sent": result.get("sent", False), "bytes": result.get("bytes")})

    return {
        "sent": len(results),
        "live": live,
        "duration": schedule[-1]["at"],
        "results": results,
    }


def summarize(path: str | Path) -> dict:
    record = load(path)
    events = record["events"]
    addresses = {}
    for event in events:
        addresses[event["address"]] = addresses.get(event["address"], 0) + 1
    return {
        "path": str(path),
        "name": record["meta"].get("name") or Path(path).stem,
        "created_at": record["meta"].get("created_at"),
        "events": len(events),
        "duration": round(record["duration"], 2),
        "addresses": addresses,
    }
