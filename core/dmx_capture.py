"""Captura de tramas DMX a disco, para analizar después sin la consola delante.

Qué es: un archivo donde cada línea es un frame de 512 canales, con su universo y su
instante. Los canales van comprimidos (zlib + base64) porque un rig real cambia poco
entre frames: 20 KB/s en crudo bajan a ~1 KB/s.

Qué no es: un reproductor. Guardar es pasivo; emitir DMX sería otro producto y otra
decisión de seguridad, así que aquí no se envía nada.

Formato `.dmxcap` (JSONL):

    {"v":1,"kind":"meta","created_at":"...","universes":[1,2]}
    {"v":1,"kind":"frame","t":0.042,"u":1,"d":"eJx..."}   # 512 bytes comprimidos

Herramientas: `summary()` para saber qué se grabó y `export_csv()` para abrir un
universo concreto en una hoja de cálculo.
"""

from __future__ import annotations

import base64
import json
import zlib
from datetime import datetime, timezone
from pathlib import Path

DMX_SIZE = 512


def _slug(text: str) -> str:
    keep = [ch.lower() if ch.isalnum() else "-" for ch in (text or "captura")]
    return "".join(keep).strip("-")[:40] or "captura"


class DmxCapture:
    """Escribe frames a un `.dmxcap`. Se cierra siempre, incluso si algo falla."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")
        self._start = None
        self.frames = 0
        self.universes: set[int] = set()
        meta = {
            "v": 1,
            "kind": "meta",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "universes": [],
        }
        self._handle.write(json.dumps(meta, ensure_ascii=False) + "\n")
        self._handle.flush()

    def write(self, frame) -> None:
        """Sink compatible con DmxMonitor: recibe un Frame."""
        if self._handle.closed:
            return
        if self._start is None:
            self._start = frame.received_at
        payload = base64.b64encode(zlib.compress(bytes(frame.channels), 1)).decode("ascii")
        elapsed = round(frame.received_at - self._start, 3)
        self._last_t = max(getattr(self, "_last_t", 0.0), elapsed)
        line = {
            "v": 1,
            "kind": "frame",
            "t": elapsed,
            "u": int(frame.universe),
            "d": payload,
        }
        self._handle.write(json.dumps(line) + "\n")
        self.frames += 1
        self.universes.add(int(frame.universe))

    def close(self) -> dict:
        if not self._handle.closed:
            self._handle.flush()
            self._handle.close()
        return {
            "path": str(self.path),
            "frames": self.frames,
            "universes": sorted(self.universes),
            "seconds": round(self._last_t, 2) if hasattr(self, "_last_t") else 0.0,
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def new_capture(directory: str | Path, name: str) -> DmxCapture:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return DmxCapture(Path(directory) / f"{stamp}_{_slug(name)}.dmxcap")


def read_meta(path: str | Path) -> dict:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"No existe la captura: {target}")
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("kind") == "meta":
                return row
    return {}


def iter_frames(path: str | Path):
    """Genera dicts {t, universe, channels} decodificando al vuelo."""
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") != "frame":
                continue
            try:
                channels = tuple(zlib.decompress(base64.b64decode(row["d"])))
            except (KeyError, ValueError, zlib.error):
                continue
            yield {"t": float(row.get("t", 0.0)), "universe": int(row.get("u", 0)), "channels": channels}


def summary(path: str | Path) -> dict:
    """Cuenta frames, duración y qué canales se movieron de verdad."""
    meta = read_meta(path)
    per_universe: dict[int, dict] = {}
    total = 0
    duration = 0.0
    for frame in iter_frames(path):
        total += 1
        duration = max(duration, frame["t"])
        stats = per_universe.setdefault(frame["universe"], {"frames": 0, "active": set(), "peak": 0})
        stats["frames"] += 1
        stats["peak"] = max(stats["peak"], max(frame["channels"]) if frame["channels"] else 0)
        stats["active"].update(i + 1 for i, value in enumerate(frame["channels"]) if value)
    return {
        "path": str(path),
        "created_at": meta.get("created_at"),
        "frames": total,
        "seconds": round(duration, 2),
        "fps": round(total / duration, 1) if duration else 0.0,
        "universes": [
            {
                "universe": universe,
                "frames": stats["frames"],
                "active_channels": len(stats["active"]),
                "peak": stats["peak"],
            }
            for universe, stats in sorted(per_universe.items())
        ],
    }


def list_captures(directory: str | Path, *, limit: int = 20) -> list[dict]:
    """Capturas recientes con un resumen corto, para listarlas en la app."""
    base = Path(directory)
    if not base.is_dir():
        return []
    found = []
    for path in sorted(base.glob("*.dmxcap"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            info = summary(path)
        except (OSError, ValueError):
            continue
        found.append(
            {
                "name": path.name,
                "frames": info["frames"],
                "seconds": info["seconds"],
                "universes": [u["universe"] for u in info["universes"]],
                "kb": round(path.stat().st_size / 1024, 1),
            }
        )
    return found


def export_csv(path: str | Path, universe: int, out: str | Path) -> dict:
    """Una fila por frame, una columna por canal. Sólo canales que se movieron."""
    target = Path(out)
    frames = [frame for frame in iter_frames(path) if frame["universe"] == int(universe)]
    if not frames:
        raise ValueError(f"No hay frames del universo {universe}")
    active = sorted({i + 1 for frame in frames for i, value in enumerate(frame["channels"]) if value})
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write("t," + ",".join(f"ch{channel}" for channel in active) + "\n")
        for frame in frames:
            values = ",".join(str(frame["channels"][channel - 1]) for channel in active)
            handle.write(f"{frame['t']},{values}\n")
    return {"path": str(target), "rows": len(frames), "channels": len(active)}
