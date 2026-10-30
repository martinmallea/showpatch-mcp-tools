#!/usr/bin/env python3
"""Porta el kit de orquestación a otro proyecto.

Copia el orquestador, el registro de lecciones y las plantillas de equipo, y
genera un plan de trabajo mínimo con gates reales (no verdes de mentira: si no
hay tests, el gate falla y el work package no se declara hecho).

Uso:
    python tools/scaffold_project.py --dest C:\\proyectos\\mi-app --name mi-app
    cd C:\\proyectos\\mi-app
    python orchestrate.py status
    python orchestrate.py brief WP-01
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KIT_FILES = (
    "orchestrator/__init__.py",
    "orchestrator/plan.py",
    "orchestrator/state.py",
    "orchestrator/evidence.py",
    "orchestrator/cli.py",
    "tools/lessons.py",
)

SHIM = '''#!/usr/bin/env python3
"""Orquestador del proyecto (kit portado desde showpatch).

    python orchestrate.py status
    python orchestrate.py next
    python orchestrate.py brief WP-01
    python orchestrate.py gate WP-01
    python orchestrate.py run
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
'''

ROLES_TEMPLATE = """# Equipo de agentes — {name}

Kit portado desde `showpatch`. Tres reglas lo sostienen: **un dueño por ruta**,
**un gate por work package** y **una lección por error pagado**.

## Roles

| Rol | Para qué | Escribe en |
|---|---|---|
| ORQ | Reparte, verifica y desbloquea. No implementa | `orchestration/`, `agents/` |
| SUB-QA | Contrato, tests y verificación integral | `tests/`, `tools/` de verificación |
| SUB-PARSER | Ingesta y normalización de datos externos | parsers del proyecto |
| SUB-GEOMETRY | Cálculo y transformaciones | motores de dominio |
| SUB-PROTOCOL | APIs, protocolos y transporte | servidores y clientes |
| SUB-DOCS | Arquitectura, release y changelog | `docs/`, `CHANGELOG.md` |

## Ciclo de un work package

```bash
python orchestrate.py next            # qué está listo
python orchestrate.py brief WP-01     # encargo autocontenido (incluye lecciones)
# el subagente ejecuta y devuelve rutas + salida de tests
python orchestrate.py gate WP-01      # se acepta sólo si el gate pasa
```

Estados: `pending → in_progress → done | failed | blocked`. `blocked` es
legítimo: significa "no se puede demostrar aquí".

## Experiencia acumulada

Cada error no obvio se registra y **se inyecta en los briefs siguientes** del
mismo rol:

```bash
python orchestrate.py --help                 # comandos del orquestador
python -c "from tools import lessons; lessons.add('SUB-QA', 'titulo', 'detalle', wp='WP-01')"
```

El fichero es `agents/lessons.jsonl` (una lección por línea). Si una lección deja
de aplicar, se borra la línea: el registro es memoria operativa, no un archivo
histórico.

## Al despertar un agente

Su brief ya trae objetivo, rutas que posee, criterio de aceptación, gates y las
últimas lecciones del rol. No hace falta explicarle el proyecto desde cero.

## Reglas duras

1. No se escribe fuera de las rutas del work package.
2. No se declara hecho lo que el gate no demuestra.
3. Lo que dependa de hardware o software ausente se reporta como `blocked`.
4. Un cambio de contrato exige su propio work package.
"""

PLAN_TEMPLATE = {
    "project": "{name}",
    "contract_version": "0.1.0",
    "updated_at": "{today}",
    "notes": "Plantilla: renombra los work packages y cambia los gates por los reales del proyecto.",
    "work_packages": [
        {
            "id": "WP-01",
            "title": "Primer test que falla y luego pasa",
            "owner": "SUB-QA",
            "depends_on": [],
            "paths": ["tests/"],
            "deliverable": "Suite mínima ejecutable que demuestre el comportamiento acordado.",
            "definition_of_done": [
                "Existe al menos un test que describe el comportamiento esperado",
                "La suite corre con un solo comando",
            ],
            "gates": [
                {
                    "id": "G-TESTS",
                    "type": "command",
                    "argv": ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                    "cwd": ".",
                }
            ],
            "brief": "Objetivo: convertir la intención en una prueba ejecutable.\n\n"
            "Regla: el primer test debe fallar por la razón correcta antes de escribir la "
            "implementación. Si el gate no puede pasar todavía, el WP queda blocked, no done.",
        },
        {
            "id": "WP-02",
            "title": "Primera funcionalidad de dominio",
            "owner": "SUB-PROTOCOL",
            "depends_on": ["WP-01"],
            "paths": ["src/"],
            "deliverable": "Implementación mínima cubierta por los tests de WP-01.",
            "definition_of_done": [
                "El comportamiento acordado está implementado",
                "Los tests de WP-01 pasan sin tocarlos",
            ],
            "gates": [
                {
                    "id": "G-SUITE",
                    "type": "command",
                    "argv": ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                    "cwd": ".",
                }
            ],
            "brief": "Objetivo: implementar sin renegociar el contrato de los tests.\n\n"
            "Si el test estaba mal, se corrige el test y se explica por qué; no se relaja "
            "la aserción para poner verde.",
        },
        {
            "id": "WP-03",
            "title": "Documentación de arranque",
            "owner": "SUB-DOCS",
            "depends_on": ["WP-02"],
            "paths": ["README.md", "docs/"],
            "deliverable": "README que permita a otro arrancar el proyecto sin preguntar.",
            "definition_of_done": [
                "Comandos copiables y verificados",
                "Estado real: qué funciona, qué no y qué falta",
            ],
            "gates": [{"id": "G-README", "type": "file", "path": "README.md"}],
            "brief": "Objetivo: que otro retome el proyecto sin ti.\n\n"
            "Nada de promesas sin verificar: separa 'funciona', 'sin probar' y 'pendiente'.",
        },
    ],
}

ROSTER_TEMPLATE = {
    "project": "{name}",
    "contract_version": "0.1.0",
    "platform_agents": {"note": "Rellena agentId si registras estos roles en la app."},
    "roles": [
        {"role": role, "platform_agent": None, "agent_id": None, "owns": []}
        for role in ("ORQ", "SUB-QA", "SUB-PARSER", "SUB-GEOMETRY", "SUB-PROTOCOL", "SUB-DOCS")
    ],
    "hard_rules": [
        "Un dueño por ruta: nadie escribe fuera de su work package.",
        "Ningún work package se declara hecho sin gate en verde y evidencia.",
        "Lo que no se pueda demostrar se reporta como blocked.",
        "Un cambio de contrato exige work package propio.",
    ],
}


def scaffold(destination: Path, name: str, *, force: bool = False) -> list[str]:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()) and not force:
        raise SystemExit(f"{destination} no está vacío. Usa --force para escribir igualmente.")
    destination.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for relative in KIT_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"Falta en el kit: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        created.append(relative)

    today = datetime.now(timezone.utc).date().isoformat()
    payloads = {
        "orchestrate.py": SHIM,
        "orchestration/work_packages.json": json.dumps(
            json.loads(json.dumps(PLAN_TEMPLATE).replace("{name}", name).replace("{today}", today)),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "agents/ROLES.md": ROLES_TEMPLATE.replace("{name}", name),
        "agents/roster.json": json.dumps(
            json.loads(json.dumps(ROSTER_TEMPLATE).replace("{name}", name)), ensure_ascii=False, indent=2
        )
        + "\n",
        "agents/lessons.jsonl": "",
    }
    for relative, content in payloads.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        created.append(relative)

    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Porta el kit de orquestación a otro proyecto")
    parser.add_argument("--dest", required=True, help="carpeta destino (se crea si no existe)")
    parser.add_argument("--name", required=True, help="nombre del proyecto")
    parser.add_argument("--force", action="store_true", help="escribir aunque el destino no esté vacío")
    args = parser.parse_args(argv)

    created = scaffold(Path(args.dest), args.name, force=args.force)
    print(f"Kit instalado en {Path(args.dest).resolve()} ({len(created)} archivos)")
    for relative in created:
        print(f"  + {relative}")
    print("\nSiguiente paso:")
    print(f"  cd {args.dest}")
    print("  python orchestrate.py status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
