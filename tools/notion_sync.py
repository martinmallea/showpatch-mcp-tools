"""Estructura el proyecto en Notion: espejo del repo y bundle importable.

Dos caminos, porque el token no siempre está:

1. **Bundle** (`--bundle`): genera `exports/notion/` con páginas Markdown y bases de
   datos en CSV. Se importa en Notion a mano (Import → Markdown & CSV) y funciona
   sin API. Es lo que puedes hacer hoy.
2. **Sync** (`--apply`): crea una página ShowPatch, cuatro bases de datos y
   vuelca work packages, lecciones y releases con la API. Requiere token.

Regla de diseño: **el repo manda**. Notion es un espejo para humanos; nunca se
edita allí el estado y se espera que vuelva. Un sync de ida evita el conflicto
clásico de "dos fuentes de verdad".

    python tools/notion_sync.py --dry-run
    python tools/notion_sync.py --bundle
    python tools/notion_sync.py --apply --parent <page_id>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPORTS = ROOT / "exports"
BUNDLE = EXPORTS / "notion"
IDS_FILE = EXPORTS / "notion_ids.json"
API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
SLEEP = 0.35  # ~3 req/s, el límite documentado por Notion


# --------------------------------------------------------------------------- datos


def load_plan() -> dict:
    return json.loads((ROOT / "orchestration" / "work_packages.json").read_text(encoding="utf-8"))


def load_state() -> dict:
    path = ROOT / "orchestration" / "state.json"
    if not path.is_file():
        return {"work_packages": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def load_lessons() -> list[dict]:
    from tools import lessons

    return lessons.read()


def releases() -> list[dict]:
    """Extrae versiones del CHANGELOG (título y fecha)."""
    path = ROOT / "CHANGELOG.md"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## [") and "]" in line:
            version = line.split("[", 1)[1].split("]", 1)[0]
            rest = line.split("]", 1)[1].strip(" —-")
            out.append({"version": version, "date": rest})
    return out


DECISIONS = [
    {
        "id": "D-01",
        "title": "Congelar el contrato antes de portar código",
        "context": "El handoff traía 19 archivos y decía 6/6, pero ejecutaba 4/6.",
        "decision": "Primero se audita y arregla el contrato; después se escribe lo que falta.",
        "consequence": "Ninguna feature puede justificar un cambio de esquema.",
    },
    {
        "id": "D-02",
        "title": "La IA no emite DMX crudo",
        "context": "Jitter y latencia de un LLM rompen el ritmo de un show.",
        "decision": "La IA escribe comandos de consola; la consola renderiza.",
        "consequence": "Sin Art-Net de salida. Reproducir DMX sería otro producto y otro modelo de seguridad.",
    },
    {
        "id": "D-03",
        "title": "Los parsers no calculan Pan",
        "context": "El prototipo mezclaba geometría y lectura de patch.",
        "decision": "Los parsers emiten semantic vacío; sólo la geometría escribe bearing y Pan.",
        "consequence": "Se puede probar cada capa por separado y auditar el origen del dato.",
    },
    {
        "id": "D-04",
        "title": "Allowlist de verbos y dry-run por defecto",
        "context": "Un comando mal escrito en una consola en vivo es un blackout.",
        "decision": "Sólo salen verbos conocidos; todo envío es simulado salvo petición explícita.",
        "consequence": "Más fricción para el operador, cero sustos.",
    },
    {
        "id": "D-05",
        "title": "El índice de fixtures es el último recurso",
        "context": "14 221 fixtures de terceros pueden estar mal.",
        "decision": "Regex y diccionarios resuelven antes; el índice sólo rellena huecos y marca su origen.",
        "consequence": "El contrato no depende de datos externos.",
    },
]


def work_package_rows() -> list[dict]:
    plan = load_plan()
    state = load_state().get("work_packages", {})
    rows = []
    for package in plan.get("work_packages", []):
        wid = package["id"]
        record = state.get(wid, {})
        gates = package.get("gates", [])
        evidence = record.get("evidence") or []
        rows.append(
            {
                "ID": wid,
                "Titulo": package.get("title", ""),
                "Estado": record.get("status", "pending"),
                "Owner": package.get("owner", ""),
                "DependeDe": ", ".join(package.get("depends_on") or []),
                "Gate": " | ".join(
                    gate.get("path") or " ".join(gate.get("argv", [])).replace("{python}", "python")
                    for gate in gates
                ),
                "Evidencia": evidence[-1] if evidence else "",
                "Rutas": ", ".join(package.get("paths") or []),
            }
        )
    return rows


def lesson_rows() -> list[dict]:
    rows = []
    for entry in load_lessons():
        rows.append(
            {
                "Titulo": entry.get("title", ""),
                "Rol": entry.get("role", ""),
                "WP": entry.get("wp", ""),
                "Detalle": entry.get("detail", ""),
                "Fecha": (entry.get("ts") or "")[:10],
            }
        )
    return rows


def release_rows() -> list[dict]:
    rows = []
    for item in releases():
        version = item["version"]
        rows.append({"Version": version, "Fecha": item["date"], "Notas": "Ver CHANGELOG.md"})
    return rows


# ------------------------------------------------------------------- bundle local


def build_bundle(target: Path = BUNDLE) -> dict:
    """Genera Markdown + CSV importables en Notion sin API."""
    target.mkdir(parents=True, exist_ok=True)
    (target / "roadmap.csv").write_text("", encoding="utf-8")
    rows = work_package_rows()
    with (target / "roadmap.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["ID"])
        writer.writeheader()
        writer.writerows(rows)

    lessons_data = lesson_rows()
    with (target / "lecciones.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Titulo", "Rol", "WP", "Detalle", "Fecha"])
        writer.writeheader()
        writer.writerows(lessons_data)

    with (target / "releases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Version", "Fecha", "Notas"])
        writer.writeheader()
        writer.writerows(release_rows())

    with (target / "decisiones.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ID", "Decision", "Contexto", "Consecuencia"])
        writer.writeheader()
        for item in DECISIONS:
            writer.writerow(
                {"ID": item["id"], "Decision": item["title"], "Contexto": item["context"], "Consecuencia": item["consequence"]}
            )

    (target / "00 Portada.md").write_text(PORTADA.format(today=date.today().isoformat()), encoding="utf-8")
    (target / "01 Vision.md").write_text(VISION, encoding="utf-8")
    (target / "02 Arquitectura.md").write_text((ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8"), encoding="utf-8")
    (target / "03 Operacion.md").write_text(OPERACION, encoding="utf-8")
    (target / "04 Roadmap.md").write_text(ROADMAP_MD, encoding="utf-8")
    return {"dir": str(target), "files": sorted(p.name for p in target.iterdir())}


PORTADA = """# ShowPatch · estructura del proyecto

Este espacio es el **espejo legible** del repositorio. La fuente de verdad es el
repo: `orchestration/work_packages.json` manda sobre estas tablas.

- **Roadmap**: los 15 work packages con owner, gate y evidencia.
- **Lecciones**: errores ya pagados, por rol.
- **Releases**: versiones y número de tests.
- **Decisiones**: por qué el sistema es como es.

Actualizado el {today}.
"""

VISION = """# Visión

## Qué es

Un puente entre un LLM y tres consolas de iluminación (grandMA3, ChamSys y
Wolfmix). El modelo no escribe DMX: escribe comandos de consola y la consola
renderiza.

## Para quién

Programadores y técnicos que llegan a un recinto distinto con el mismo rig y
tienen menos tiempo del que necesitan.

## Qué duele y qué resuelve

| Dolor | Respuesta |
|---|---|
| Dos aparatos en la misma dirección | Detector de solapes de patch |
| El rig no cabe en el escenario | Herradura y matriz afín idempotentes |
| Clon sin manual | Índice de 14 221 fixtures |
| Color a ojo | RGB/CMY/HSV/RGBW con % exactos y simulación de daltonismo |
| Repetir un pase de focos | Grabador de comandos con autoplay |

## Principio que no se negocia

La IA nunca emite DMX. Si el puente falla, la consola sigue haciendo el show.
"""

OPERACION = """# Operación

```bash
python bridge.py verify                 # puerta única: contrato + tests
python bridge.py orchestrate status     # estado de los work packages
python bridge.py orchestrate brief WP-03
python bridge.py orchestrate gate WP-03
python bridge.py web                    # app local (panel, fixtures, DMX, color)
python bridge.py rec --new pase         # grabador de comandos
python bridge.py landing                # landing con registro
```

## Rutas

- Repo: `showpatch/`
- Plan: `orchestration/work_packages.json`
- Evidencia: `orchestration/evidence/`
- Lecciones: `agents/lessons.jsonl`
- App: `web/static/panel.html`
- Landing: `landing/index.html`
"""

ROADMAP_MD = """# Roadmap

| ID | Título | Owner | Estado |
|---|---|---|---|
| WP-01 | Contrato congelado en verde | SUB-QA | done |
| WP-02 | Parsers de consola | SUB-PARSER | done |
| WP-03 | Motor geométrico | SUB-GEOMETRY | done |
| WP-04 | Finder DMX | SUB-PARSER | done |
| WP-05 | Emisores MA3/ChamSys | SUB-PROTOCOL | done |
| WP-06 | Servidor MCP + OSC | SUB-PROTOCOL | done |
| WP-07 | Orquestador y equipo | ORQ | done |
| WP-08 | Auditoría de entorno | SUB-QA | done |
| WP-09 | Verificación integral | SUB-QA | done |
| WP-10 | Documentación de release | SUB-DOCS | done |
| WP-11 | Índice de fixtures | SUB-PARSER | done |
| WP-12 | Rebranding a ShowPatch | ORQ | done |
| WP-13 | App local y calculadoras | SUB-PROTOCOL | done |
| WP-14 | Grabador y autoplay | SUB-PROTOCOL | done |
| WP-15 | Landing con registro | SUB-DOCS | done |
| WP-16 | Estructura en Notion | SUB-DOCS | done |
| WP-17 | Captura DMX por red (sACN/Art-Net) | — | pendiente |

La tabla viva es `roadmap.csv`: Notion la convierte en base de datos al importar.
"""


# ------------------------------------------------------------------- API Notion


class NotionError(RuntimeError):
    pass


class Notion:
    """Cliente mínimo. El transporte se inyecta para poder probar sin red."""

    def __init__(self, token: str, *, transport=None, version: str = VERSION):
        self.token = token
        self.version = version
        self._transport = transport or self._http
        self.calls = 0

    def _http(self, method: str, path: str, payload: dict | None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            API + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.version,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise NotionError(f"{method} {path} → {exc.code}: {detail}") from exc

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        self.calls += 1
        time.sleep(SLEEP)
        return self._transport(method, path, payload)

    # --- primitivas de payload

    @staticmethod
    def title(text: str) -> dict:
        return {"title": [{"text": {"content": (text or "")[:1900]}}]}

    @staticmethod
    def rich(text: str) -> dict:
        return {"rich_text": [{"text": {"content": (text or "")[:1900]}}]}

    @staticmethod
    def select(text: str) -> dict:
        return {"select": {"name": text}} if text else {"select": None}


def token_from_disk() -> str | None:
    candidate = Path.home() / ".config" / "notion" / "api_key"
    if candidate.is_file():
        value = candidate.read_text(encoding="utf-8").strip()
        return value or None
    return os.environ.get("NOTION_KEY") or None


def data_source_payload(page_id: str, title: str, properties: dict) -> dict:
    return {"parent": {"page_id": page_id}, "title": [{"text": {"content": title}}], "properties": properties}


ROADMAP_PROPS = {
    "ID": {"title": {}},
    "Titulo": {"rich_text": {}},
    "Estado": {"select": {"options": [{"name": n} for n in ("pending", "in_progress", "done", "failed", "blocked")]}},
    "Owner": {"select": {"options": [{"name": n} for n in ("ORQ", "SUB-QA", "SUB-PARSER", "SUB-GEOMETRY", "SUB-PROTOCOL", "SUB-DOCS")]}},
    "DependeDe": {"rich_text": {}},
    "Gate": {"rich_text": {}},
    "Evidencia": {"rich_text": {}},
    "Rutas": {"rich_text": {}},
}

LESSON_PROPS = {
    "Titulo": {"title": {}},
    "Rol": {"rich_text": {}},
    "WP": {"rich_text": {}},
    "Detalle": {"rich_text": {}},
    "Fecha": {"date": {}},
}

RELEASE_PROPS = {"Version": {"title": {}}, "Fecha": {"date": {}}, "Notas": {"rich_text": {}}}


def page_payload(database_id: str, properties: dict) -> dict:
    return {"parent": {"database_id": database_id}, "properties": properties}


def apply(token: str, parent_page_id: str, *, transport=None, ids_file: Path = IDS_FILE) -> dict:
    """Crea (o reutiliza) la estructura y vuelca los datos."""
    client = Notion(token, transport=transport)
    ids_file.parent.mkdir(parents=True, exist_ok=True)
    ids = json.loads(ids_file.read_text(encoding="utf-8")) if ids_file.is_file() else {}

    if "page" not in ids:
        page = client.request("POST", "/pages", {"parent": {"page_id": parent_page_id}, "properties": {"title": Notion.title("ShowPatch")}})
        ids["page"] = page["id"]
        ids_file.write_text(json.dumps(ids, indent=2), encoding="utf-8")

    page_id = ids["page"]
    for key, title, props in (
        ("roadmap", "Roadmap", ROADMAP_PROPS),
        ("lessons", "Lecciones", LESSON_PROPS),
        ("releases", "Releases", RELEASE_PROPS),
    ):
        if key not in ids:
            created = client.request("POST", "/data_sources", data_source_payload(page_id, title, props))
            ids[key] = {"database_id": created["id"], "data_source_id": created.get("id")}
            ids_file.write_text(json.dumps(ids, indent=2), encoding="utf-8")

    created = 0
    for row in work_package_rows():
        properties = {
            "ID": Notion.title(row["ID"]),
            "Titulo": Notion.rich(row["Titulo"]),
            "Estado": Notion.select(row["Estado"]),
            "Owner": Notion.select(row["Owner"]),
            "DependeDe": Notion.rich(row["DependeDe"]),
            "Gate": Notion.rich(row["Gate"]),
            "Evidencia": Notion.rich(row["Evidencia"]),
            "Rutas": Notion.rich(row["Rutas"]),
        }
        client.request("POST", "/pages", page_payload(ids["roadmap"]["database_id"], properties))
        created += 1

    for row in lesson_rows():
        properties = {
            "Titulo": Notion.title(row["Titulo"]),
            "Rol": Notion.rich(row["Rol"]),
            "WP": Notion.rich(row["WP"]),
            "Detalle": Notion.rich(row["Detalle"]),
            "Fecha": {"date": {"start": row["Fecha"]}} if row["Fecha"] else {"date": None},
        }
        client.request("POST", "/pages", page_payload(ids["lessons"]["database_id"], properties))
        created += 1

    return {"page_id": page_id, "items": created, "calls": client.calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estructura ShowPatch en Notion")
    parser.add_argument("--bundle", action="store_true", help="generar Markdown + CSV importables")
    parser.add_argument("--dry-run", action="store_true", help="mostrar qué se enviaría")
    parser.add_argument("--apply", action="store_true", help="crear en Notion (requiere token y --parent)")
    parser.add_argument("--parent", default=None, help="page_id de la página contenedora")
    args = parser.parse_args(argv)

    if args.bundle:
        result = build_bundle()
        print(f"Bundle en {result['dir']} ({len(result['files'])} archivos):")
        for name in result["files"]:
            print(f"  + {name}")
        print("\nEn Notion: Import → Markdown & CSV → elige la carpeta.")
        return 0

    payload = {
        "work_packages": work_package_rows(),
        "lessons": lesson_rows(),
        "releases": release_rows(),
        "decisions": DECISIONS,
    }

    if args.apply:
        token = token_from_disk()
        if not token:
            print("Falta el token: crea ~/.config/notion/api_key o define NOTION_KEY.", file=sys.stderr)
            return 2
        if not args.parent:
            print("Falta --parent con el page_id de una página compartida con la integración.", file=sys.stderr)
            return 2
        result = apply(token, args.parent)
        print(f"Listo: página {result['page_id']} · {result['items']} items · {result['calls']} llamadas")
        return 0

    EXPORTS.mkdir(exist_ok=True)
    out = EXPORTS / "notion_payloads.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Dry-run:")
    print(f"  work packages: {len(payload['work_packages'])}")
    print(f"  lecciones: {len(payload['lessons'])}")
    print(f"  releases: {len(payload['releases'])}")
    print(f"  decisiones: {len(payload['decisions'])}")
    print(f"  payload completo: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
