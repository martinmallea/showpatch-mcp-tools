"""Evidencia reproducible: huella del repo + resultado de cada gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "orchestration" / "evidence"

TRACKED_SUFFIXES = {".py", ".json", ".md", ".xml", ".yml", ".yaml", ".lua", ".sh", ".ps1", ".txt"}
EXCLUDED_PARTS = {".git", "__pycache__", "generated", "evidence", ".pytest_cache", "venv", ".venv"}
EXCLUDED_NAMES = {"state.json"}


def tracked_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TRACKED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.name in EXCLUDED_NAMES:
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p.relative_to(root)).lower())


def fingerprint(root: Path = ROOT) -> str:
    """SHA-256 del contenido del repo (provenance de una verificación)."""
    digest = hashlib.sha256()
    for path in tracked_files(root):
        relative = str(path.relative_to(root)).replace("\\", "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def run_gate(gate: dict, root: Path = ROOT, *, timeout: int = 600) -> dict:
    """Ejecuta un gate y devuelve su resultado, sin lanzar excepciones."""
    started = datetime.now(timezone.utc)
    kind = gate.get("type")
    result = {
        "gate": gate.get("id"),
        "type": kind,
        "ok": False,
        "argv": [],
        "exit": None,
        "duration_ms": 0,
        "stdout_tail": "",
        "stderr_tail": "",
    }

    if kind == "file":
        target = root / str(gate.get("path", ""))
        result["path"] = str(gate.get("path"))
        result["ok"] = target.is_file()
        if not result["ok"]:
            result["stderr_tail"] = f"No existe el archivo: {result['path']}"
        result["duration_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        return result

    argv = [str(sys.executable) if part == "{python}" else str(part) for part in gate.get("argv", [])]
    cwd = root / str(gate.get("cwd", "."))
    result["argv"] = argv
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        result["exit"] = completed.returncode
        result["stdout_tail"] = (completed.stdout or "")[-4000:]
        result["stderr_tail"] = (completed.stderr or "")[-4000:]
        expected = int(gate.get("expect_exit", 0))
        result["ok"] = completed.returncode == expected
    except (OSError, subprocess.SubprocessError) as exc:
        result["stderr_tail"] = f"{type(exc).__name__}: {exc}"
    result["duration_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return result


def write_evidence(work_package_id: str, results: list[dict], *, directory: Path | None = None) -> Path:
    target_dir = Path(directory) if directory else EVIDENCE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = target_dir / f"{work_package_id}_{stamp}.json"
    payload = {
        "work_package": work_package_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(),
        "ok": all(item["ok"] for item in results),
        "gates": results,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
