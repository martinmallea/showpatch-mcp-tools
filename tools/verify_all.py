#!/usr/bin/env python3
"""Puerta única de verificación: contrato + módulos + ejemplo del esquema.

Un solo comando, un solo exit code. Si algo está rojo, no se publica.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def check_contract(quiet: bool) -> tuple[bool, str]:
    completed = _run([sys.executable, "tools/contract_test.py", "--json"])
    try:
        results = json.loads(completed.stdout)
        passed = sum(1 for item in results if item.get("passed"))
        total = len(results)
    except json.JSONDecodeError:
        return False, "contrato: salida JSON ilegible"
    ok = completed.returncode == 0 and passed == total and total == 6
    return ok, f"contrato: {passed}/{total} PASS"


def check_unittest(quiet: bool) -> tuple[bool, str]:
    completed = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    output = (completed.stderr or "") + (completed.stdout or "")
    match = re.search(r"Ran (\d+) tests?", output)
    count = match.group(1) if match else "?"
    ok = completed.returncode == 0 and "OK" in output
    return ok, f"módulos: {count} tests {'OK' if ok else 'FALLAN'}"


def check_example() -> tuple[bool, str]:
    from core.schema_validator import validate_show

    path = ROOT / "spec" / "unified_show-1.0.0.example.json"
    example = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_show(example, post_parser=False)
    return (not errors), "esquema: ejemplo válido" if not errors else f"esquema: {len(errors)} errores"


def check_roundtrip() -> tuple[bool, str]:
    """Un rig de 6 fixtures debe sobrevivir a herradura + traducción + validación."""
    from core.commands import translate
    from core.intelligence import horseshoe
    from core.schema_validator import validate_show

    example = json.loads((ROOT / "spec" / "unified_show-1.0.0.example.json").read_text(encoding="utf-8"))
    seed = example.get("fixtures") or []
    if not seed:
        return False, "roundtrip: el ejemplo no tiene fixtures"

    rig = copy.deepcopy(example)
    rig["fixtures"] = []
    for index in range(6):
        clone = copy.deepcopy(seed[index % len(seed)])
        clone["id"] = str(11 + index)
        clone["name"] = f"Rig_{index + 1}"
        rig["fixtures"].append(clone)

    shaped = horseshoe(rig, radius=4.0)
    errors = validate_show(shaped, post_parser=False)
    commands = translate(shaped, "grandMA3")["commands"]
    ok = not errors and len(commands) >= 6
    return ok, (
        f"roundtrip: herradura 6/6 + {len(commands)} comandos OK"
        if ok
        else f"roundtrip: roto ({len(errors)} errores, {len(commands)} comandos)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verificación integral")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    checks = [check_contract, check_unittest, lambda quiet: check_example(), lambda quiet: check_roundtrip()]
    results = [check(args.quiet) for check in checks]

    print("SHOWPATCH — verificación integral\n" + "=" * 44)
    for ok, label in results:
        print(f"{'✅' if ok else '❌'} {label}")
    total_ok = all(ok for ok, _ in results)
    print("=" * 44)
    print("RESULTADO:", "TODO VERDE" if total_ok else "HAY FALLOS")
    return 0 if total_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
