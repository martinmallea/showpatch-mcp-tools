#!/usr/bin/env python3
"""Auditoría del entorno: qué hay instalado, qué falta y qué bloquea cada hueco.

No instala nada. Genera ``docs/ENVIRONMENT.json`` (máquina) y
``docs/ENVIRONMENT.md`` (humano) para que la decisión de instalar sea informada.

    python bridge.py audit            # escribe y resume
    python bridge.py audit --json     # imprime el inventario
    python bridge.py audit --check    # falla si un hueco imprescindible no tiene remediación
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

WINDOWS = platform.system() == "Windows"

# level: required = sin esto no se puede cerrar el roadmap; optional = mejora.
PROBES: tuple[dict, ...] = (
    {
        "key": "python",
        "command": sys.executable,
        "version_args": ["--version"],
        "level": "required",
        "purpose": "Ejecuta core, tests, orquestador y servidor MCP.",
        "blocks": [],
        "remediation": "ya instalado (intérprete embebido de la aplicación)",
    },
    {
        "key": "git",
        "command": "git",
        "version_args": ["--version"],
        "level": "required",
        "purpose": "Versionado local, ramas, tags y trazabilidad de la evidencia.",
        "blocks": [],
        "remediation": "winget install --id Git.Git -e" if WINDOWS else "apt install git",
    },
    {
        "key": "gh",
        "command": "gh",
        "version_args": ["--version"],
        "level": "required",
        "purpose": "Crear el repositorio, push, PRs y protección de rama.",
        "blocks": ["WP-10"],
        "remediation": "winget install --id GitHub.cli -e" if WINDOWS else "apt install gh",
    },
    {
        "key": "pandoc",
        "command": "pandoc",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Convertir PROJECT_OVERVIEW.md y docs a PDF.",
        "blocks": [],
        "remediation": "winget install --id JohnMacFarlane.Pandoc -e" if WINDOWS else "apt install pandoc",
    },
    {
        "key": "lua",
        "command": "lua",
        "version_args": ["-v"],
        "level": "optional",
        "purpose": "Validar sintaxis de ma3_plugins/mcp_state_bridge.lua antes de subirlo a la consola.",
        "blocks": [],
        "remediation": "winget install --id DEVCOM.Lua -e" if WINDOWS else "apt install lua5.4",
    },
    {
        "key": "luac",
        "command": "luac",
        "version_args": ["-v"],
        "level": "optional",
        "purpose": "Compilar el plugin Lua en local (luac -p) como control de sintaxis.",
        "blocks": [],
        "remediation": "winget install --id DEVCOM.Lua -e" if WINDOWS else "apt install lua5.4",
    },
    {
        "key": "node",
        "command": "node",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Clientes MCP en JS y utilidades de desarrollo.",
        "blocks": [],
        "remediation": "winget install --id OpenJS.NodeJS.LTS -e" if WINDOWS else "apt install nodejs",
    },
    {
        "key": "rg",
        "command": "rg",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Búsqueda rápida en el repo (usada por la app, no por el código).",
        "blocks": [],
        "remediation": "winget install --id BurntSushi.ripgrep.MSVC -e" if WINDOWS else "apt install ripgrep",
    },
    {
        "key": "ssh",
        "command": "ssh",
        "version_args": ["-V"],
        "level": "optional",
        "purpose": "Acceso remoto a consolas o a la máquina de show.",
        "blocks": [],
        "remediation": "winget install --id Microsoft.OpenSSH.Beta -e" if WINDOWS else "apt install openssh-client",
    },
    {
        "key": "curl",
        "command": "curl",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Pruebas HTTP contra la API web de ChamSys.",
        "blocks": [],
        "remediation": "winget install --id cURL.cURL -e" if WINDOWS else "apt install curl",
    },
    {
        "key": "docker",
        "command": "docker",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Reproducir el CI de GitHub (ubuntu-latest) en local.",
        "blocks": [],
        "remediation": "winget install --id Docker.DockerDesktop -e" if WINDOWS else "apt install docker.io",
    },
    {
        "key": "wsl",
        "command": "wsl",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Shell Linux para scripts .sh del repo (bootstrap_repo.sh).",
        "blocks": [],
        "remediation": "wsl --install -d Ubuntu",
    },
    {
        "key": "code",
        "command": "code",
        "version_args": ["--version"],
        "level": "optional",
        "purpose": "Edición y exportación Markdown → PDF desde VS Code.",
        "blocks": [],
        "remediation": "winget install --id Microsoft.VisualStudioCode -e" if WINDOWS else "snap install code",
    },
)

SHOW_ROOTS = (
    Path("C:/Program Files/MA Lighting Technologies"),
    Path("C:/Program Files (x86)/MA Lighting Technologies"),
    Path("C:/ProgramData/MALightingTechnology"),
    Path("C:/Program Files/ChamSys Ltd"),
    Path("C:/Program Files (x86)/ChamSys Ltd"),
    Path(os.environ.get("LOCALAPPDATA", "C:/Users")) / "Programs",
)

CONSOLES = (
    {
        "key": "grandMA3 onPC",
        "prefixes": ("gma3",),
        "version_pattern": r"(\d+\.\d+\.\d+)",
        "purpose": "Validar /gma3/cmd, el plugin Lua y el estado OSC de MA3.",
    },
    {
        "key": "grandMA2 onPC",
        "prefixes": ("gma2",),
        "version_pattern": r"(\d+\.\d+\.\d+(?:\.\d+)?)",
        "purpose": "Consola soportada por el esquema (source.system=grandMA2), con OSC distinto.",
    },
    {
        "key": "ChamSys MagicQ PC",
        "prefixes": ("mqqt", "mqhd", "mqvis"),
        "version_pattern": r"(\d+\.\d+\.\d+(?:\.\d+)?)",
        "purpose": "Validar el import CSV y los comandos ChamSys.",
    },
)


def _probe(tool: dict) -> dict:
    command = tool["command"]
    resolved = command if Path(command).is_file() else shutil.which(command)
    record = {
        "key": tool["key"],
        "level": tool["level"],
        "purpose": tool["purpose"],
        "blocks": list(tool.get("blocks", [])),
        "remediation": tool.get("remediation", ""),
        "path": resolved,
        "version": "",
        "status": "missing" if not resolved else "present",
        "note": "",
    }
    if not resolved:
        return record
    try:
        completed = subprocess.run(
            [resolved, *tool["version_args"]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
        record["version"] = first_line[:120]
    except (OSError, subprocess.SubprocessError) as exc:
        record["note"] = f"no se pudo leer la versión: {type(exc).__name__}"
    if record["key"] == "wsl" and record["status"] == "present":
        record["note"], record["status"] = _wsl_state(resolved)
    return record


def _wsl_state(resolved: str) -> tuple[str, str]:
    """WSL instalado sin distribución no sirve para ejecutar los .sh del repo."""
    try:
        completed = subprocess.run(
            [resolved, "--list", "--quiet"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        output = (completed.stdout or "").replace("\x00", "")
    except (OSError, subprocess.SubprocessError):
        return "estado indeterminado", "partial"

    # Sin distribución, wsl.exe imprime el banner de ayuda en vez de una lista.
    markers = ("Copyright", "Uso:", "Usage:", "--install", "Argumentos:")
    if any(marker in output for marker in markers):
        return "sólo el lanzador instalado, sin distribución Linux", "partial"
    distros = [line.strip() for line in output.splitlines() if line.strip()]
    if distros:
        return f"distribuciones: {', '.join(distros)}", "present"
    return "sin distribución instalada (sólo el lanzador)", "partial"


def _walk(root: Path, max_depth: int = 4, limit: int = 4000) -> list[Path]:
    """Recorrido acotado en profundidad y número, para no arrastrar el disco."""
    found: list[Path] = []
    if not root.exists():
        return found
    base_depth = len(root.parts)
    for current, directories, files in os.walk(root):
        if len(Path(current).parts) - base_depth >= max_depth:
            directories[:] = []
        for name in files:
            found.append(Path(current) / name)
            if len(found) >= limit:
                return found
    return found


def _scan_console_software() -> list[dict]:
    """Detecta consolas instaladas por ejecutable, con su versión si es legible."""
    files: list[Path] = []
    for root in SHOW_ROOTS:
        files.extend(_walk(root))
    lowered = [(path, path.name.lower()) for path in files]

    results = []
    for console in CONSOLES:
        executables = [
            path
            for path, name in lowered
            if name.endswith(".exe") and name.startswith(console["prefixes"])
        ]
        version = ""
        for executable in executables:
            match = re.search(console["version_pattern"], str(executable.parent))
            if match:
                version = match.group(1)
                break
        entry = {
            "key": console["key"],
            "purpose": console["purpose"],
            "detected": bool(executables),
            "version": version,
            "executables": [str(path) for path in executables[:5]],
            "paths": sorted({str(path.parent) for path in executables})[:5],
            "note": "",
        }
        if not executables:
            data_dirs = sorted(
                {
                    str(path)
                    for path, name in lowered
                    if console["prefixes"][0] in name and path.is_dir()
                }
            )[:3]
            entry["paths"] = data_dirs
            if data_dirs:
                entry["note"] = "sólo datos/librería en disco, sin ejecutable onPC"
            else:
                entry["note"] = "no encontrado"
        results.append(entry)
    return results



def build_inventory() -> dict:
    tools = [_probe(tool) for tool in PROBES]
    consoles = _scan_console_software()
    required_missing = [t["key"] for t in tools if t["level"] == "required" and t["status"] != "present"]
    optional_missing = [t["key"] for t in tools if t["level"] == "optional" and t["status"] != "present"]
    ma3 = next((c for c in consoles if c["key"] == "grandMA3 onPC"), None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "python_safe_path": bool(getattr(sys.flags, "safe_path", False)),
            "root": str(ROOT),
        },
        "summary": {
            "tools_probed": len(tools),
            "present": sum(1 for t in tools if t["status"] == "present"),
            "missing": sum(1 for t in tools if t["status"] == "missing"),
            "partial": sum(1 for t in tools if t["status"] == "partial"),
            "required_missing": required_missing,
            "optional_missing": optional_missing,
            "unactionable_gaps": [
                t["key"] for t in tools if t["status"] != "present" and not t["remediation"]
            ],
            "console_target_installed": bool(ma3 and ma3["detected"]),
        },
        "tools": tools,
        "show_software": consoles,
    }


def _icon(status: str) -> str:
    return {"present": "✅", "partial": "⚠️", "missing": "❌"}.get(status, "?")


def render_markdown(inventory: dict) -> str:
    summary = inventory["summary"]
    platform_info = inventory["platform"]
    lines: list[str] = [
        "# Entorno de ejecución — inventario verificado",
        "",
        f"Generado por `python bridge.py audit` el **{inventory['generated_at']}**.",
        "No se instala nada: este documento describe el estado real y el coste de cada hueco.",
        "",
        "## Plataforma",
        "",
        f"- SO: **{platform_info['system']} {platform_info['release']}** ({platform_info['version']})",
        f"- Arquitectura: `{platform_info['machine']}`",
        f"- Python: **{platform_info['python']}** — `{platform_info['python_executable']}`",
        f"- `sys.flags.safe_path` = `{platform_info['python_safe_path']}`"
        + (" (por eso la CLI es `python bridge.py`, no `python -m`)" if platform_info["python_safe_path"] else ""),
        f"- Raíz del proyecto: `{platform_info['root']}`",
        "",
        "## Resumen",
        "",
        f"- Herramientas sondeadas: **{summary['tools_probed']}**",
        f"- Presentes: **{summary['present']}** · Ausentes: **{summary['missing']}** · Parciales: **{summary['partial']}**",
        f"- Huecos imprescindibles: **{', '.join(summary['required_missing']) or 'ninguno'}**",
        f"- Huecos deseables: **{', '.join(summary['optional_missing']) or 'ninguno'}**",
        "",
        "## Herramientas imprescindibles",
        "",
        "| | Herramienta | Versión | Ruta | Para qué |",
        "|---|---|---|---|---|",
    ]
    for tool in inventory["tools"]:
        if tool["level"] != "required":
            continue
        lines.append(
            f"| {_icon(tool['status'])} | `{tool['key']}` | {tool['version'] or '—'} | "
            f"`{tool['path'] or 'no encontrado'}` | {tool['purpose']} |"
        )

    lines += [
        "",
        "## Herramientas deseables",
        "",
        "| | Herramienta | Versión | Estado | Para qué |",
        "|---|---|---|---|---|",
    ]
    for tool in inventory["tools"]:
        if tool["level"] != "optional":
            continue
        detail = tool["version"] or tool["note"] or "—"
        if tool["status"] == "partial" and tool["note"]:
            detail = f"{detail} — {tool['note']}"
        lines.append(
            f"| {_icon(tool['status'])} | `{tool['key']}` | {tool['version'] or '—'} | "
            f"{tool['status']} | {tool['purpose']} |"
        )

    lines += ["", "## Huecos y remediación", ""]
    gaps = [t for t in inventory["tools"] if t["status"] != "present"]
    if not gaps:
        lines.append("No hay huecos: todo lo sondeado está instalado.")
    else:
        lines += ["| Herramienta | Estado | Bloquea | Comando para cerrarlo |", "|---|---|---|---|"]
        for tool in gaps:
            blocks = ", ".join(tool["blocks"]) or "—"
            lines.append(
                f"| `{tool['key']}` | {tool['status']} | {blocks} | `{tool['remediation'] or 'sin remediación conocida'}` |"
            )

    lines += ["", "## Software de consola detectado", ""]
    missing_target = not inventory["summary"].get("console_target_installed", False)
    if missing_target:
        lines += [
            "> ⚠️ **El proyecto apunta a grandMA3 y esta máquina no tiene el ejecutable de",
            "> grandMA3 onPC.** Sí hay grandMA2 onPC instalado. Consecuencia: se puede probar",
            "> el patch y los comandos MA2, pero NO `/gma3/cmd`, ni el plugin Lua de MA3, ni",
            "> el estado OSC tal como está implementado. Cualquier validación de punta a punta",
            "> contra MA3 requiere instalar grandMA3 onPC (misma versión que la consola destino).",
            "",
        ]
    lines += ["| | Consola | Versión | Ejecutables | Nota |", "|---|---|---|---|---|"]
    for entry in inventory["show_software"]:
        icon = "✅" if entry["detected"] else "❌"
        executables = ", ".join(f"`{Path(p).name}`" for p in entry["executables"]) or "—"
        lines.append(
            f"| {icon} | {entry['key']} | {entry['version'] or 'no declarada'} | {executables} | {entry['note'] or entry['purpose']} |"
        )
    lines += ["", "Rutas relevantes:", ""]
    for entry in inventory["show_software"]:
        paths = ", ".join(f"`{p}`" for p in entry["paths"]) or "—"
        lines.append(f"- **{entry['key']}**: {paths}")

    lines += [
        "",
        "## Qué se puede automatizar hoy, en esta máquina",
        "",
        "- ✅ Contrato, tests, esquema y validación de documentos: sólo requiere Python.",
        "- ✅ Servidor MCP por stdio y simulación OSC (`dry_run`): sólo requiere Python.",
        "- ✅ Versionado local con git y generación de evidencia con hash.",
        "- ⚠️ Envío OSC real: Python puede emitir el datagrama, pero la verificación de "
        "recepción necesita una consola o un listener en la misma subred.",
        "- ❌ Publicación en GitHub: falta `gh` (git por sí solo no crea el remoto ni PRs).",
        "- ❌ Validación de sintaxis del plugin Lua: falta `lua`/`luac`.",
        "- ❌ Exportación a PDF de la documentación: falta `pandoc`.",
        "- ⚠️ Paridad con el CI de GitHub (ubuntu-latest): `wsl.exe` existe pero sin distribución Linux; falta Docker o una distro WSL.",
        "",
        "## Límites de hardware (no detectables por software)",
        "",
        "Ninguna comprobación local sustituye a la prueba física. Siguen pendientes:",
        "",
        "1. grandMA3 onPC con Node 2-Port: el nodo **no libera parámetros**; la licencia de "
        "onPC es la que habilita el recuento (2 048 en onPC; los nodos suman según modelo).",
        "2. Latencia y pérdida reales de OSC/UDP: no hay ACK, la confirmación se hace con "
        "el listener de estado o con el plugin Lua residente.",
        "3. Comportamiento del yugo real frente a `pan_offset_deg`: el offset calibrado en "
        "`core/pan_offsets.py` es una hipótesis hasta medirlo en el fixture.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auditoría del entorno")
    parser.add_argument("--json", action="store_true", help="imprime el inventario JSON")
    parser.add_argument("--check", action="store_true", help="falla si un hueco no tiene remediación")
    args = parser.parse_args(argv)

    inventory = build_inventory()
    DOCS.mkdir(exist_ok=True)
    json_path = DOCS / "ENVIRONMENT.json"
    md_path = DOCS / "ENVIRONMENT.md"
    json_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(inventory), encoding="utf-8")

    if args.json:
        print(json.dumps(inventory, indent=2, ensure_ascii=False))
        return 0

    summary = inventory["summary"]
    print("SHOWPATCH — auditoría de entorno")
    print("=" * 44)
    print(f"presentes {summary['present']} · ausentes {summary['missing']} · parciales {summary['partial']}")
    print(f"imprescindibles ausentes: {', '.join(summary['required_missing']) or 'ninguno'}")
    print(f"deseables ausentes: {', '.join(summary['optional_missing']) or 'ninguno'}")
    print(f"escrito: docs/ENVIRONMENT.md + docs/ENVIRONMENT.json")

    if args.check:
        if summary["unactionable_gaps"]:
            print(f"❌ huecos sin remediación: {', '.join(summary['unactionable_gaps'])}")
            return 3
        print("✅ todo hueco tiene remediación documentada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
