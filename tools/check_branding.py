#!/usr/bin/env python3
"""Gate de rebranding: falla si reaparece el nombre antiguo del proyecto.

Se ejecuta como gate de WP-12. Excluye la evidencia histórica (no se reescribe)
y a sí mismo, que por definición contiene los tokens prohibidos.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("ma-ai-bridge", "ma ai bridge")
SKIP_PARTS = {"evidence", ".git", "__pycache__", "generated"}
SUFFIXES = {".py", ".md", ".json", ".yml", ".yaml", ".txt", ".lua", ".sh", ".ps1"}
SELF = Path(__file__).name


def scan() -> list[str]:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if path.name == SELF or any(part in SKIP_PARTS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN:
            if token in text:
                hits.append(f"{path.relative_to(ROOT).as_posix()}: {token}")
    return hits


def main() -> int:
    hits = scan()
    if hits:
        print("Restos del nombre antiguo:")
        for hit in hits:
            print(f"  - {hit}")
        return 1
    print("OK: sin restos de 'ma-ai-bridge' ni 'MA AI Bridge' en archivos versionados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
