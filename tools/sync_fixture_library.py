#!/usr/bin/env python3
"""Sincroniza el índice de fixtures de ChamSys Fixture Finder.

Qué se obtiene (API pública del buscador, sin autenticación):

    GET /api/v1/meta                 -> versión de la librería y recuentos
    GET /api/v1/manufacturers        -> fabricantes con número de cabezas
    GET /api/v1/library/all?page=N   -> 300 entradas/página: id, fabricante,
                                        modelo, modo, canales y archivo .hed
    GET /api/v1/fixtures/{id}        -> detalle con all_chans (funciones reales)
    GET /api/v1/fixtures/{id}/modes  -> modos alternativos con su conteo

Se guarda SÓLO metadatos (nombre, modo, número de canales). No se descargan los
binarios .hed ni se redistribuyen: el índice es una referencia para resolver
"Robe Pointe Extended" -> 31 canales sin abrir la consola.

Uso:
    python tools/sync_fixture_library.py                 # fabricantes curados
    python tools/sync_fixture_library.py --all           # catálogo completo (~70k)
    python tools/sync_fixture_library.py --manufacturers "Robe,Clay Paky"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://fixturefinder.chamsys.co.uk/api/v1"
DEFAULT_OUT = ROOT / "spec" / "fixture_library.json"
PER_PAGE = 300
USER_AGENT = "showpatch/1.0 (fixture metadata sync; contacto: operador local)"

# Fabricantes que cubren el caso real del proyecto: touring (Robe, Clay Paky,
# Martin) y el grueso de clones chinos y gamas de entrada que llegan a bolo.
CURATED = (
    "Robe", "Clay Paky", "ClayPaky", "Martin", "Acme", "ADJ", "Elation",
    "Chauvet", "Chauvet Professional", "Ayra", "Showtec", "Shehds", "Generic",
    "BeamZ", "Cameo", "Stairville", "Eurolite", "JB Systems", "Ignition",
    "Varytec", "Solena", "Fun Generation",
)


def fetch_json(url: str, *, retries: int = 3, delay: float = 1.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = delay * 4 * attempt
                print(f"  429 rate limit; espero {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if attempt == retries:
                raise
            time.sleep(delay * attempt)
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
            time.sleep(delay * attempt)
    raise RuntimeError(f"sin respuesta: {url}")


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def iter_catalog(*, delay: float, max_pages: int | None = None):
    """Recorre el catálogo página a página (300 por página)."""
    page = 1
    while True:
        if max_pages and page > max_pages:
            return
        payload = fetch_json(f"{BASE}/library/all?page={page}")
        rows = payload.get("data") or []
        meta = payload.get("meta") or {}
        last = meta.get("last_page")
        total = meta.get("total")
        print(f"  página {page}/{last or '?'} ({len(rows)} filas, total {total or '?'})", file=sys.stderr)
        if not rows:
            return
        for row in rows:
            yield row
        if last and page >= int(last):
            return
        if len(rows) < PER_PAGE:
            return
        page += 1
        time.sleep(delay)


def build_index(manufacturers: tuple[str, ...] | None, *, delay: float, max_pages: int | None) -> dict:
    meta = fetch_json(f"{BASE}/meta")
    print(f"librería {meta.get('version')} · {meta.get('head_count')} cabezas · {meta.get('manufacturer_count')} fabricantes", file=sys.stderr)
    wanted = {_norm(name) for name in manufacturers} if manufacturers else None

    entries: list[dict] = []
    seen: set[int] = set()
    for row in iter_catalog(delay=delay, max_pages=max_pages):
        if wanted is not None and _norm(row.get("m", "")) not in wanted:
            continue
        identifier = row.get("id")
        if identifier in seen:
            continue
        seen.add(identifier)
        entries.append(
            {
                "id": identifier,
                "manufacturer": row.get("m"),
                "model": row.get("n"),
                "mode": row.get("o"),
                "channels": row.get("c"),
                "file": row.get("f"),
            }
        )

    entries.sort(key=lambda item: (_norm(item["manufacturer"]), _norm(item["model"]), item["channels"] or 0))
    return {
        "source": "https://fixturefinder.chamsys.co.uk/",
        "api": BASE,
        "library_version": meta.get("version"),
        "library_heads": meta.get("head_count"),
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "all" if wanted is None else sorted(manufacturers or ()),
        "count": len(entries),
        "note": "Metadatos de referencia (fabricante, modelo, modo, canales). "
                "No se distribuyen binarios .hed. © ChamSys; uso de interoperabilidad.",
        "fixtures": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sincroniza el índice de fixtures de ChamSys")
    parser.add_argument("--all", action="store_true", help="catálogo completo (~70k entradas)")
    parser.add_argument("--manufacturers", default=None, help="lista separada por comas")
    parser.add_argument("--delay", type=float, default=0.6, help="segundos entre páginas")
    parser.add_argument("--max-pages", type=int, default=None, help="límite de páginas (pruebas)")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    if args.all:
        manufacturers = None
    else:
        manufacturers = tuple(row.strip() for row in (args.manufacturers or ",".join(CURATED)).split(",") if row.strip())

    index = build_index(manufacturers, delay=args.delay, max_pages=args.max_pages)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    size_kb = out.stat().st_size / 1024
    print(f"OK {index['count']} fixtures -> {out} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
