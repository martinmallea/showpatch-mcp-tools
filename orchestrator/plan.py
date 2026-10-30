"""Carga y validación del plan de trabajo (DAG de work packages)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN = ROOT / "orchestration" / "work_packages.json"

KNOWN_OWNERS = {
    "ORQ",
    "SUB-QA",
    "SUB-PARSER",
    "SUB-GEOMETRY",
    "SUB-PROTOCOL",
    "SUB-DOCS",
}


class PlanError(ValueError):
    """El plan no es ejecutable: ids duplicados, dependencias rotas o ciclos."""


def load_plan(path: str | Path | None = None) -> dict:
    plan_path = Path(path) if path else DEFAULT_PLAN
    if not plan_path.exists():
        raise PlanError(f"No existe el plan: {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"Plan con JSON inválido: {exc}") from exc
    problems = validate_plan(plan)
    if problems:
        raise PlanError("Plan inválido:\n  - " + "\n  - ".join(problems))
    return plan


def validate_plan(plan: dict) -> list[str]:
    """Devuelve la lista de problemas; vacía significa plan ejecutable."""
    problems: list[str] = []
    if not isinstance(plan, dict):
        return ["El plan debe ser un objeto JSON"]
    packages = plan.get("work_packages")
    if not isinstance(packages, list) or not packages:
        return ["Falta 'work_packages' o está vacío"]

    ids: list[str] = []
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            problems.append(f"work_packages[{index}] no es un objeto")
            continue
        wid = package.get("id")
        if not isinstance(wid, str) or not wid:
            problems.append(f"work_packages[{index}] sin 'id'")
            continue
        if wid in ids:
            problems.append(f"Id duplicado: {wid}")
        ids.append(wid)
        if not package.get("title"):
            problems.append(f"{wid}: falta 'title'")
        owner = package.get("owner")
        if owner not in KNOWN_OWNERS:
            problems.append(f"{wid}: owner desconocido {owner!r}")
        if not isinstance(package.get("depends_on", []), list):
            problems.append(f"{wid}: 'depends_on' debe ser lista")
        gates = package.get("gates")
        if not isinstance(gates, list) or not gates:
            problems.append(f"{wid}: sin gates (no sería verificable)")
        else:
            for gate in gates:
                gid = gate.get("id") if isinstance(gate, dict) else None
                kind = gate.get("type") if isinstance(gate, dict) else None
                if not gid:
                    problems.append(f"{wid}: gate sin 'id'")
                if kind == "command" and not gate.get("argv"):
                    problems.append(f"{wid}/{gid}: gate command sin 'argv'")
                elif kind == "file" and not gate.get("path"):
                    problems.append(f"{wid}/{gid}: gate file sin 'path'")
                elif kind not in ("command", "file"):
                    problems.append(f"{wid}/{gid}: tipo de gate no soportado {kind!r}")

    known = set(ids)
    for package in packages:
        wid = package.get("id")
        for dependency in package.get("depends_on", []) or []:
            if dependency not in known:
                problems.append(f"{wid}: depende de {dependency!r}, que no existe")
            if dependency == wid:
                problems.append(f"{wid}: se declara dependiente de sí mismo")

    if not problems:
        try:
            topological_order(plan)
        except PlanError as exc:
            problems.append(str(exc))
    return problems


def work_packages(plan: dict) -> dict[str, dict]:
    return {package["id"]: package for package in plan["work_packages"]}


def topological_order(plan: dict) -> list[str]:
    """Orden de ejecución estable (Kahn, desempate por id)."""
    packages = work_packages(plan)
    pending = {wid: set(p.get("depends_on") or []) for wid, p in packages.items()}
    order: list[str] = []
    while pending:
        ready = sorted(wid for wid, deps in pending.items() if not deps)
        if not ready:
            blocked = ", ".join(sorted(pending))
            raise PlanError(f"Ciclo de dependencias entre: {blocked}")
        for wid in ready:
            order.append(wid)
            pending.pop(wid)
        for deps in pending.values():
            deps.difference_update(ready)
    return order


def is_ready(plan: dict, state: dict, work_package_id: str) -> bool:
    """Un WP está listo si todas sus dependencias están en 'done'."""
    packages = work_packages(plan)
    package = packages[work_package_id]
    for dependency in package.get("depends_on") or []:
        if state.get("work_packages", {}).get(dependency, {}).get("status") != "done":
            return False
    status = state.get("work_packages", {}).get(work_package_id, {}).get("status")
    return status not in ("done", "in_progress")


def ready_ids(plan: dict, state: dict) -> list[str]:
    return [wid for wid in topological_order(plan) if is_ready(plan, state, wid)]
