"""Registro de experiencia acumulada del equipo de agentes.

Una lección es un error ya pagado o una decisión que funcionó. Se guardan en
JSONL append-only y se inyectan automáticamente en cada brief del orquestador,
para que el siguiente subagente no repita el mismo tropiezo.

Formato de línea:
    {"ts": "...", "project": "...", "role": "SUB-QA", "wp": "WP-01",
     "title": "...", "detail": "...", "tags": ["contrato"]}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "agents" / "lessons.jsonl"

MAX_TITLE = 120
MAX_DETAIL = 600


def add(
    role: str,
    title: str,
    detail: str,
    *,
    wp: str | None = None,
    project: str | None = None,
    tags: tuple[str, ...] | list[str] = (),
    path: str | Path | None = None,
) -> dict:
    """Añade una lección y la devuelve. Falla si falta lo esencial."""
    role = (role or "ALL").strip()
    title = (title or "").strip()
    detail = (detail or "").strip()
    if not title or not detail:
        raise ValueError("Una lección necesita 'title' y 'detail'")
    if len(title) > MAX_TITLE:
        raise ValueError(f"El título no puede pasar de {MAX_TITLE} caracteres")
    if len(detail) > MAX_DETAIL:
        raise ValueError(f"El detalle no puede pasar de {MAX_DETAIL} caracteres")

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": project or ROOT.name,
        "role": role,
        "wp": wp or "",
        "title": title,
        "detail": detail,
        "tags": list(tags),
    }
    target = Path(path) if path else DEFAULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read(path: str | Path | None = None) -> list[dict]:
    """Lee las lecciones, ignorando líneas corruptas (un log no debe romper el flujo)."""
    target = Path(path) if path else DEFAULT_PATH
    if not target.is_file():
        return []
    entries = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("title"):
            entries.append(entry)
    return entries


def recent(role: str | None = None, *, limit: int = 5, path: str | Path | None = None) -> list[dict]:
    """Últimas lecciones, opcionalmente filtradas por rol (incluye las globales)."""
    entries = read(path)
    if role:
        role_key = role.strip().upper()
        entries = [e for e in entries if str(e.get("role", "")).upper() in (role_key, "ALL")]
    return entries[-limit:]


def format_for_brief(role: str | None = None, *, limit: int = 5, path: str | Path | None = None) -> str:
    """Bloque markdown listo para pegar en un brief. Vacío si no hay experiencia."""
    entries = recent(role, limit=limit, path=path)
    if not entries:
        return ""
    lines = []
    for entry in entries:
        where = f" [{entry.get('wp')}]" if entry.get("wp") else ""
        lines.append(f"- **{entry['title']}**{where} — {entry['detail']}")
    return "\n".join(lines)
