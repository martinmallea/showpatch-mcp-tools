"""Índice local de metadatos de fixtures (ChamSys Fixture Finder).

Problema que resuelve: el texto de patch de una consola casi nunca declara los
canales. `split_fixture_type_string` cubre lo evidente (regex "24ch") y una lista
corta de modelos de touring, pero un rig real trae cientos de modelos. Aquí hay
un índice de ~13 700 cabezas de 17 fabricantes para cerrar ese hueco.

Sólo metadatos: fabricante, modelo, modo, número de canales y nombre del .hed.
No hay binarios ni definiciones de canal del fabricante.

Fuente: https://fixturefinder.chamsys.co.uk/api/v1 (público, sin autenticación).
Regenerable con `python bridge.py fixtures --sync`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "spec" / "fixture_library.json"

_CACHE: dict[tuple[str, float], dict] = {}


def normalize(text: str) -> str:
    """Clave de comparación: ASCII, minúsculas, sólo alfanumérico.

    Así "MAC Aura XB", "MAC_Aura_XB" y "mac aura xb" colapsan en la misma clave.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_text.lower() if ch.isalnum())


def load(path: str | Path | None = None) -> dict:
    target = Path(path) if path else DEFAULT_PATH
    if not target.is_file():
        return {"fixtures": [], "count": 0, "missing": True, "path": str(target)}
    stamp = target.stat().st_mtime
    key = (str(target), stamp)
    if key in _CACHE:
        return _CACHE[key]
    document = json.loads(target.read_text(encoding="utf-8"))
    document["missing"] = False
    document["path"] = str(target)
    _CACHE.clear()
    _CACHE[key] = document
    return document


def entries(path: str | Path | None = None) -> list[dict]:
    return load(path).get("fixtures", [])


def search(
    manufacturer: str | None = None,
    model: str | None = None,
    *,
    limit: int = 10,
    path: str | Path | None = None,
) -> list[dict]:
    """Búsqueda por subcadena normalizada, para uso humano/CLI."""
    mfr_key = normalize(manufacturer) if manufacturer else ""
    model_key = normalize(model) if model else ""
    found = []
    for row in entries(path):
        if mfr_key and mfr_key not in normalize(row.get("manufacturer")):
            continue
        if model_key and model_key not in normalize(row.get("model")):
            continue
        found.append(row)
        if len(found) >= limit:
            break
    return found


def _pack(row: dict, ambiguous: bool, group: list[dict]) -> dict:
    options = sorted(
        {(row.get("mode") or "—", row.get("channels")) for row in group},
        key=lambda item: (item[1] or 0, str(item[0])),
    )
    channels = row.get("channels")
    return {
        "id": row.get("id"),
        "manufacturer": row.get("manufacturer"),
        "model": row.get("model"),
        "mode": row.get("mode"),
        "channels": int(channels) if isinstance(channels, int) else None,
        "file": row.get("file"),
        "ambiguous": ambiguous,
        "options": [{"mode": mode, "channels": count} for mode, count in options],
    }


def resolve(
    manufacturer: str,
    model: str,
    mode: str | None = None,
    *,
    path: str | Path | None = None,
) -> dict | None:
    """Resuelve fabricante+modelo (+modo) a un conteo de canales.

    Devuelve ``None`` si no hay match. Si hay varios modos y ninguno se pidió
    explícitamente, elige el más frecuente y marca ``ambiguous=True``: es una
    hipótesis, no un dato.
    """
    model_key = normalize(model)
    if not model_key:
        return None
    mfr_key = normalize(manufacturer)
    rows = entries(path)

    group = [
        row
        for row in rows
        if normalize(row.get("model")) == model_key
        and (not mfr_key or normalize(row.get("manufacturer")) == mfr_key)
    ]
    if not group and mfr_key:
        group = [
            row
            for row in rows
            if normalize(row.get("manufacturer")) == mfr_key and model_key in normalize(row.get("model"))
        ]
    if not group:
        return None

    if mode:
        mode_key = normalize(mode)
        for row in group:
            if normalize(row.get("mode")) == mode_key:
                return _pack(row, False, group)
        digits = re.sub(r"\D", "", mode)
        if digits:
            for row in group:
                if str(row.get("channels")) == digits:
                    return _pack(row, False, group)

    by_count: dict[int | None, list[dict]] = {}
    for row in group:
        by_count.setdefault(row.get("channels"), []).append(row)
    if len(by_count) == 1:
        return _pack(next(iter(by_count.values()))[0], False, group)

    best_count, best_rows = max(by_count.items(), key=lambda item: (len(item[1]), -(item[0] or 0)))
    del best_count
    return _pack(best_rows[0], True, group)


def summary() -> dict:
    document = load()
    return {
        "available": not document.get("missing", False),
        "count": document.get("count", len(document.get("fixtures", []))),
        "library_version": document.get("library_version"),
        "synced_at": document.get("synced_at"),
        "source": document.get("source"),
        "path": document.get("path"),
    }
