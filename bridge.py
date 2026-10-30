#!/usr/bin/env python3
"""Punto de entrada único del proyecto.

Existe porque el intérprete puede arrancar con ``safe_path`` (sin el directorio
actual en ``sys.path``): así ``python bridge.py`` funciona siempre, sin depender
del cwd ni de variables de entorno.

    python bridge.py mcp            # servidor MCP por stdio
    python bridge.py contract       # suite de contrato (6 tests)
    python bridge.py test           # unittest de módulos
    python bridge.py verify         # puerta única: contrato + módulos + esquema
    python bridge.py audit          # auditoría del entorno instalado
    python bridge.py orchestrate …  # plan / status / brief / gate / run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(argv: list[str], *, cwd: Path | None = None) -> int:
    completed = subprocess.run(argv, cwd=str(cwd or ROOT))
    return completed.returncode


def cmd_mcp(args: argparse.Namespace) -> int:
    from mcp_server.server import run_stdio

    return run_stdio()


def cmd_contract(args: argparse.Namespace) -> int:
    argv = [sys.executable, str(ROOT / "tools" / "contract_test.py")]
    if args.verbose:
        argv.append("--verbose")
    return _run(argv)


def cmd_test(args: argparse.Namespace) -> int:
    return _run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", args.pattern, "-v"]
    )


def cmd_verify(args: argparse.Namespace) -> int:
    from tools.verify_all import main as verify_main

    return verify_main(["--quiet"] if args.quiet else [])


def cmd_audit(args: argparse.Namespace) -> int:
    from tools.env_audit import main as audit_main

    argv: list[str] = []
    if args.check:
        argv.append("--check")
    if args.json:
        argv.append("--json")
    return audit_main(argv)


def cmd_fixtures(args: argparse.Namespace) -> int:
    if args.sync:
        from tools.sync_fixture_library import main as sync_main

        argv: list[str] = []
        if args.all:
            argv.append("--all")
        if args.manufacturers:
            argv += ["--manufacturers", args.manufacturers]
        return sync_main(argv)

    from core.fixture_library import search, summary

    info = summary()
    if not info["available"]:
        print("Índice no disponible. Genéralo con: python bridge.py fixtures --sync")
        return 3
    if not args.search and not args.manufacturer:
        print(f"Índice: {info['count']} fixtures · librería {info['library_version']} · {info['synced_at']}")
        print(f"Origen: {info['source']}")
        print("Uso: python bridge.py fixtures --search pointe [--manufacturer robe]")
        return 0

    rows = search(args.manufacturer, args.search, limit=args.limit)
    if not rows:
        print("Sin resultados.")
        return 4
    for row in rows:
        channel_count = row.get("channels")
        print(f"{row.get('manufacturer', '?'):<16} {row.get('model', '?'):<26} "
              f"{(row.get('mode') or '—'):<10} {str(channel_count or '?'):>4} ch   id={row.get('id')}")
    return 0


def cmd_lessons(args: argparse.Namespace) -> int:
    from tools import lessons as store

    if args.add:
        if not args.title or not args.detail:
            print("Para añadir una lección hacen falta --title y --detail")
            return 2
        entry = store.add(
            args.role or "ALL",
            args.title,
            args.detail,
            wp=args.wp,
            project=args.project,
            tags=tuple(tag.strip() for tag in (args.tags or "").split(",") if tag.strip()),
        )
        print(f"Lección registrada [{entry['role']}{'/' + entry['wp'] if entry['wp'] else ''}]: {entry['title']}")
        return 0

    entries = store.recent(args.role, limit=args.limit) if args.role else store.read()[-args.limit:]
    if not entries:
        print("Sin lecciones registradas todavía.")
        return 0
    for entry in entries:
        where = f"/{entry['wp']}" if entry.get("wp") else ""
        print(f"{entry['ts'][:10]}  [{entry['role']}{where}]  {entry['title']}")
        print(f"    {entry['detail']}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from web.app import serve

    return serve(args.host, args.port, args.token, not args.no_browser)


def cmd_rec(args: argparse.Namespace) -> int:
    import json as _json

    from core import recorder

    if args.new:
        path = recorder.new_recording(args.new)
        print(f"Grabación creada: {path}")
        print(f"Actívala con: set SHOWPATCH_RECORD={path}")
        return 0

    if args.play:
        record = recorder.load(args.play)
        result = recorder.replay(
            record, ip=args.ip, port=args.port, speed=args.speed, loops=args.loops, live=args.live
        )
        modo = "EN VIVO" if result["live"] else "dry-run"
        print(f"{result['sent']} comandos · {result['duration']}s · {modo}")
        return 0

    if args.show:
        print(_json.dumps(recorder.summarize(args.show), indent=2, ensure_ascii=False))
        return 0

    directory = recorder.DEFAULT_DIR
    files = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
    if not files:
        print(f"Sin grabaciones en {directory}")
        print("Crea una con: python bridge.py rec --new mi-sesion")
        return 0
    for path in files:
        try:
            summary = recorder.summarize(path)
        except (OSError, ValueError):
            continue
        print(f"{summary['name']:<28} {summary['events']:>4} eventos  {summary['duration']:>6.1f}s  {path.name}")
    return 0


def cmd_landing(args: argparse.Namespace) -> int:
    from landing.server import serve

    return serve(args.host, args.port, not args.no_browser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge", description="ShowPatch — CLI única")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("mcp", help="servidor MCP JSON-RPC por stdio").set_defaults(func=cmd_mcp)

    contract = subparsers.add_parser("contract", help="suite de contrato")
    contract.add_argument("--verbose", action="store_true")
    contract.set_defaults(func=cmd_contract)

    tests = subparsers.add_parser("test", help="unittest de módulos")
    tests.add_argument("-p", dest="pattern", default="test_*.py")
    tests.set_defaults(func=cmd_test)

    verify = subparsers.add_parser("verify", help="verificación integral")
    verify.add_argument("--quiet", action="store_true")
    verify.set_defaults(func=cmd_verify)

    audit = subparsers.add_parser("audit", help="auditoría del entorno")
    audit.add_argument("--check", action="store_true")
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=cmd_audit)

    fixtures = subparsers.add_parser("fixtures", help="índice de fixtures (ChamSys Fixture Finder)")
    fixtures.add_argument("--search", default=None, help="modelo a buscar")
    fixtures.add_argument("--manufacturer", default=None)
    fixtures.add_argument("--limit", type=int, default=10)
    fixtures.add_argument("--sync", action="store_true", help="regenerar el índice desde la API")
    fixtures.add_argument("--all", action="store_true", help="con --sync: catálogo completo")
    fixtures.add_argument("--manufacturers", default=None, help="con --sync: lista separada por comas")
    fixtures.set_defaults(func=cmd_fixtures)

    lessons = subparsers.add_parser("lessons", help="experiencia acumulada del equipo")
    lessons.add_argument("--add", action="store_true", help="registrar una lección")
    lessons.add_argument("--role", default=None, help="ORQ, SUB-QA, SUB-PARSER, …")
    lessons.add_argument("--wp", default=None)
    lessons.add_argument("--title", default=None)
    lessons.add_argument("--detail", default=None)
    lessons.add_argument("--project", default=None)
    lessons.add_argument("--tags", default=None, help="separados por comas")
    lessons.add_argument("--limit", type=int, default=5)
    lessons.set_defaults(func=cmd_lessons)

    web = subparsers.add_parser("web", help="app local: panel, fixtures y calculadoras")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8787)
    web.add_argument("--token", default=None)
    web.add_argument("--no-browser", action="store_true")
    web.set_defaults(func=cmd_web)

    rec = subparsers.add_parser("rec", help="grabar y reproducir comandos (autoplay)")
    rec.add_argument("--new", default=None, help="crear una grabación")
    rec.add_argument("--play", default=None, help="reproducir un fichero .jsonl")
    rec.add_argument("--show", default=None, help="resumen de una grabación")
    rec.add_argument("--list", action="store_true", help="listar grabaciones")
    rec.add_argument("--speed", type=float, default=1.0)
    rec.add_argument("--loops", type=int, default=1)
    rec.add_argument("--live", action="store_true", help="enviar de verdad (por defecto dry-run)")
    rec.add_argument("--ip", default="127.0.0.1")
    rec.add_argument("--port", type=int, default=8000)
    rec.set_defaults(func=cmd_rec)

    landing = subparsers.add_parser("landing", help="landing de captación con registro")
    landing.add_argument("--host", default="127.0.0.1")
    landing.add_argument("--port", type=int, default=8790)
    landing.add_argument("--no-browser", action="store_true")
    landing.set_defaults(func=cmd_landing)

    # 'orchestrate' se resuelve antes de argparse para pasar sus flags intactos.
    subparsers.add_parser("orchestrate", help="orquestador de work packages", add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "orchestrate":
        from orchestrator.cli import main as orchestrate_main

        return orchestrate_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "orchestrate":
        parser.error("usa 'bridge.py orchestrate <plan|status|brief|gate|run>'")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
