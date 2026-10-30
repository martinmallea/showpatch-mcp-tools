"""Estado persistente del orquestador (quién está hecho y con qué evidencia)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "orchestration" / "state.json"
VALID_STATUS = ("pending", "in_progress", "done", "failed", "blocked")


def _empty() -> dict:
    return {"version": 1, "updated_at": None, "work_packages": {}}


def load_state(path: str | Path | None = None) -> dict:
    state_path = Path(path) if path else DEFAULT_STATE
    if not state_path.exists():
        return _empty()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty()
    state.setdefault("work_packages", {})
    return state


def save_state(state: dict, path: str | Path | None = None) -> Path:
    state_path = Path(path) if path else DEFAULT_STATE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    temporary = state_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)
    return state_path


def entry(state: dict, work_package_id: str) -> dict:
    packages = state.setdefault("work_packages", {})
    return packages.setdefault(
        work_package_id,
        {"status": "pending", "attempts": 0, "evidence": [], "updated_at": None},
    )


def set_status(state: dict, work_package_id: str, status: str, *, evidence: str | None = None) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"Estado no válido: {status}")
    record = entry(state, work_package_id)
    record["status"] = status
    record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if status == "in_progress":
        record["attempts"] = int(record.get("attempts", 0)) + 1
    if evidence:
        record.setdefault("evidence", []).append(evidence)
