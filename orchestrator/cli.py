"""CLI del orquestador: planificar, despachar briefs y verificar gates.

Principio: el orquestador no ejecuta trabajo de ingeniería; decide qué se puede
hacer, quién lo posee, qué evidencia lo demuestra y si el resultado se acepta.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator import state as state_store
from orchestrator.evidence import run_gate, write_evidence
from orchestrator.plan import (
    KNOWN_OWNERS,
    PlanError,
    is_ready,
    load_plan,
    ready_ids,
    topological_order,
    work_packages,
)

ROOT = Path(__file__).resolve().parent.parent

SYMBOLS = {
    "done": "✅",
    "failed": "❌",
    "in_progress": "▶ ",
    "pending": "· ",
    "blocked": "⛔",
}


def _status_of(state: dict, work_package_id: str) -> str:
    return state.get("work_packages", {}).get(work_package_id, {}).get("status", "pending")


def _gate_commands(package: dict) -> list[str]:
    lines = []
    for gate in package.get("gates", []):
        if gate.get("type") == "file":
            lines.append(f"existe `{gate.get('path')}`")
        else:
            argv = " ".join(str(part) for part in gate.get("argv", []))
            lines.append(argv.replace("{python}", "python"))
    return lines


def _lesson_section(owner: str) -> str:
    """Experiencia acumulada del rol, inyectada en cada brief."""
    try:
        from tools import lessons as lessons_store

        block = lessons_store.format_for_brief(owner, limit=5)
    except (ImportError, OSError, ValueError):
        return ""
    if not block:
        return ""
    return f"## Lecciones previas de {owner}\n\n{block}\n\n"


def render_brief(plan: dict, state: dict, work_package_id: str) -> str:
    package = work_packages(plan)[work_package_id]
    dependencies = package.get("depends_on") or []
    dependency_lines = (
        "\n".join(f"- {dep} ({_status_of(state, dep)})" for dep in dependencies) or "- ninguna"
    )
    paths = "\n".join(f"- `{path}`" for path in package.get("paths", [])) or "- (sin rutas declaradas)"
    done = "\n".join(f"- [ ] {item}" for item in package.get("definition_of_done", []))
    gates = "\n".join(f"{index}. `{cmd}`" for index, cmd in enumerate(_gate_commands(package), 1))
    lesson_block = _lesson_section(package["owner"])
    return f"""# Brief — {work_package_id} · {package['title']}

**Owner:** {package['owner']}
**Dependencias:** {dependency_lines}
**Entregable:** {package.get('deliverable', '')}

## Objetivo y contexto

{package.get('brief', '').strip()}

## Rutas que posees (no escribas fuera de ellas)

{paths}

## Criterio de aceptación

{done}

## Gates (la única prueba válida)

{gates}

{lesson_block}Al terminar: `python bridge.py orchestrate gate {work_package_id}`.
"""


def cmd_plan(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    order = topological_order(plan)
    packages = work_packages(plan)
    if args.json:
        print(json.dumps({"order": order, "packages": packages}, indent=2, ensure_ascii=False))
        return 0
    print(f"Plan: {plan.get('project')} · contrato {plan.get('contract_version')}")
    print(f"{len(order)} work packages, {len(packages)} nodos\n")
    for position, wid in enumerate(order, 1):
        package = packages[wid]
        deps = ", ".join(package.get("depends_on") or []) or "—"
        print(f"{position:2d}. {wid}  {package['owner']:<13} deps: {deps:<28} {package['title']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    state = state_store.load_state(args.state)
    order = topological_order(plan)
    packages = work_packages(plan)
    if args.json:
        rows = [
            {
                "id": wid,
                "title": packages[wid]["title"],
                "owner": packages[wid]["owner"],
                "status": _status_of(state, wid),
                "ready": is_ready(plan, state, wid),
            }
            for wid in order
        ]
        print(json.dumps({"updated_at": state.get("updated_at"), "work_packages": rows}, indent=2, ensure_ascii=False))
        return 0
    done = sum(1 for wid in order if _status_of(state, wid) == "done")
    print(f"ShowPatch — estado del plan ({done}/{len(order)} done, updated {state.get('updated_at') or 'nunca'})")
    for wid in order:
        status = _status_of(state, wid)
        print(f"{SYMBOLS.get(status, '?')} {wid}  {status:<11} {packages[wid]['owner']:<13} {packages[wid]['title']}")
    ready = ready_ids(plan, state)
    print(f"\nListos para despachar: {', '.join(ready) if ready else 'ninguno'}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    state = state_store.load_state(args.state)
    ready = ready_ids(plan, state)
    for wid in ready:
        print(wid)
    return 0 if ready else 3


def cmd_brief(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    state = state_store.load_state(args.state)
    if args.wp not in work_packages(plan):
        print(f"Work package desconocido: {args.wp}", file=sys.stderr)
        return 2
    print(render_brief(plan, state, args.wp))
    return 0


def _run_package(package: dict, root: Path) -> list[dict]:
    return [run_gate(gate, root) for gate in package.get("gates", [])]


def _print_results(wid: str, results: list[dict]) -> None:
    for result in results:
        mark = "✅" if result["ok"] else "❌"
        detail = result.get("path") or " ".join(result.get("argv", []))
        print(f"  {mark} {result['gate']:<18} {detail}  ({result['duration_ms']} ms)")
        if not result["ok"] and result.get("stderr_tail"):
            tail = result["stderr_tail"].strip().splitlines()[-6:]
            for line in tail:
                print(f"      {line}")


def cmd_gate(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    packages = work_packages(plan)
    if args.wp not in packages:
        print(f"Work package desconocido: {args.wp}", file=sys.stderr)
        return 2
    state = state_store.load_state(args.state)
    package = packages[args.wp]
    print(f"Ejecutando gates de {args.wp} · {package['title']}")
    results = _run_package(package, ROOT)
    ok = all(result["ok"] for result in results)
    _print_results(args.wp, results)
    evidence = write_evidence(args.wp, results)
    state_store.set_status(state, args.wp, "done" if ok else "failed", evidence=str(evidence.relative_to(ROOT)))
    state_store.save_state(state, args.state)
    print(f"\nEvidencia: {evidence.relative_to(ROOT)}")
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    packages = work_packages(plan)
    order = topological_order(plan)
    state = state_store.load_state(args.state)
    targets = [args.wp] if args.wp else order
    for wid in targets:
        if wid not in packages:
            print(f"Work package desconocido: {wid}", file=sys.stderr)
            return 2

    ran = 0
    for wid in order:
        if wid not in targets:
            continue
        package = packages[wid]
        current = _status_of(state, wid)
        if current == "done" and not args.force:
            print(f"⏭  {wid} ya está done (usa --force para repetir)")
            continue
        if not args.force and not is_ready(plan, state, wid):
            missing = [d for d in package.get("depends_on") or [] if _status_of(state, d) != "done"]
            print(f"⛔ {wid} bloqueado por: {', '.join(missing) or 'dependencias no completadas'}")
            if not args.keep_going:
                return 2
            state_store.set_status(state, wid, "blocked")
            state_store.save_state(state, args.state)
            continue

        print(f"\n▶  {wid} · {package['title']} ({package['owner']})")
        state_store.set_status(state, wid, "in_progress")
        state_store.save_state(state, args.state)
        results = _run_package(package, ROOT)
        ok = all(result["ok"] for result in results)
        _print_results(wid, results)
        evidence = write_evidence(wid, results)
        state_store.set_status(state, wid, "done" if ok else "failed", evidence=str(evidence.relative_to(ROOT)))
        state_store.save_state(state, args.state)
        ran += 1
        if not ok and not args.keep_going:
            print(f"\n❌ {wid} falló. Evidencia: {evidence.relative_to(ROOT)}")
            return 1

    done = sum(1 for wid in order if _status_of(state, wid) == "done")
    print(f"\nResumen: {done}/{len(order)} done · {ran} work packages ejecutados en esta pasada")
    return 0 if done == len(order) else 3


def cmd_reset(args: argparse.Namespace) -> int:
    target = Path(args.state) if args.state else state_store.DEFAULT_STATE
    if args.wp:
        state = state_store.load_state(target)
        state.get("work_packages", {}).pop(args.wp, None)
        state_store.save_state(state, target)
        print(f"Reset: {args.wp}")
        return 0
    target.unlink(missing_ok=True)
    print(f"Estado borrado: {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrate", description="Orquestador del plan ShowPatch")
    parser.add_argument("--plan", default=None, help="ruta alternativa al plan JSON")
    parser.add_argument("--state", default=None, help="ruta alternativa al estado JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="orden topológico del DAG")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.set_defaults(func=cmd_plan)

    status_parser = subparsers.add_parser("status", help="estado de cada work package")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    next_parser = subparsers.add_parser("next", help="work packages listos")
    next_parser.set_defaults(func=cmd_next)

    brief_parser = subparsers.add_parser("brief", help="brief autocontenido para un agente")
    brief_parser.add_argument("wp")
    brief_parser.set_defaults(func=cmd_brief)

    gate_parser = subparsers.add_parser("gate", help="ejecuta y registra los gates de un WP")
    gate_parser.add_argument("wp")
    gate_parser.set_defaults(func=cmd_gate)

    run_parser = subparsers.add_parser("run", help="ejecuta el plan en orden topológico")
    run_parser.add_argument("--wp", default=None)
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--keep-going", action="store_true")
    run_parser.set_defaults(func=cmd_run)

    reset_parser = subparsers.add_parser("reset", help="borra el estado (total o de un WP)")
    reset_parser.add_argument("--wp", default=None)
    reset_parser.set_defaults(func=cmd_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PlanError as exc:
        print(f"Plan inválido: {exc}", file=sys.stderr)
        return 2


__all__ = ["main", "render_brief", "build_parser", "KNOWN_OWNERS"]
