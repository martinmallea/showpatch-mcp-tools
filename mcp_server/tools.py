"""Registro de herramientas MCP y sus implementaciones.

Cada herramienta es una función pura sobre estructuras JSON: recibe argumentos
ya validados, devuelve un dict serializable y lanza ``ToolError`` si el input no
sirve. No hay efectos de red salvo en ``osc.send``, y ése es dry-run por
defecto.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from bridges.chamsys_bridge.csv_import import parse_chamsys_csv
from bridges.ma_bridge.emitter import lua_script
from core.commands import translate
from core.finder import fingerprint
from core.intelligence import adapt, horseshoe, style_profile
from core.ma3_xml import parse_ma3_xml, parse_ma3_xml_string
from core.osc_codec import ALLOWED_ADDRESS_PREFIXES, send_message
from core.schema_validator import validate_show

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = REPO_ROOT / "generated"

# Verbos MA3 que el puente acepta. Cualquier otro se rechaza antes de enviar:
# un comando mal escrito en una consola en vivo es un blackout, no un warning.
MA3_VERBS = {
    "patch", "label", "set", "group", "clear", "store", "delete",
    "move", "copy", "assign", "appearance", "black", "flash", "swop",
}
MACRO_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Grabadora activa (si SHOWPATCH_RECORD apunta a un .jsonl). Vive aquí para que
# grabar no obligue a envolver cada llamada desde fuera.
_RECORDER = None


def _active_recorder():
    global _RECORDER
    path = os.environ.get("SHOWPATCH_RECORD")
    if not path:
        return None
    if _RECORDER is None or str(getattr(_RECORDER, "path", "")) != path:
        try:
            from core.recorder import Recorder

            _RECORDER = Recorder(path)
        except (ImportError, OSError):
            return None
    return _RECORDER


def _record(address: str, args) -> None:
    recorder_active = _active_recorder()
    if recorder_active is None:
        return
    try:
        recorder_active.append(address, list(args))
    except OSError:
        pass


class ToolError(Exception):
    """Error de argumentos o de dominio, con código JSON-RPC asociado."""

    def __init__(self, message: str, code: int = -32602):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(arguments: dict, key: str, types: tuple[type, ...], default=...):
    if key not in arguments:
        if default is ...:
            raise ToolError(f"Falta el argumento obligatorio '{key}'")
        return default
    value = arguments[key]
    if not isinstance(value, types):
        raise ToolError(
            f"'{key}' debe ser {', '.join(t.__name__ for t in types)}; "
            f"recibido {type(value).__name__}"
        )
    return value


def _resolve(path_text: str) -> Path:
    """Resuelve una ruta y la confina al repo (evita traversal)."""
    candidate = Path(path_text)
    resolved = (candidate if candidate.is_absolute() else REPO_ROOT / candidate).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ToolError(f"Ruta fuera del workspace: {path_text}") from exc
    if not resolved.exists():
        raise ToolError(f"No existe: {resolved.relative_to(REPO_ROOT)}", code=-32602)
    return resolved


def _validated(show: dict, post_parser: bool) -> dict:
    errors = validate_show(show, post_parser=post_parser)
    return {"show": show, "validation_errors": errors, "valid": not errors}


# --- Herramientas -----------------------------------------------------------


def tool_parse_ma3(arguments: dict) -> dict:
    path = _resolve(_require(arguments, "path", (str,)))
    document = parse_ma3_xml(path)
    return _validated(document, post_parser=False)


def tool_parse_ma3_text(arguments: dict) -> dict:
    text = _require(arguments, "xml", (str,))
    document = parse_ma3_xml_string(text)
    return _validated(document, post_parser=False)


def tool_parse_chamsys(arguments: dict) -> dict:
    if "path" in arguments:
        text = _resolve(_require(arguments, "path", (str,))).read_text(encoding="utf-8")
    else:
        text = _require(arguments, "csv", (str,))
    return _validated(parse_chamsys_csv(text), post_parser=False)


def tool_validate(arguments: dict) -> dict:
    show = _require(arguments, "show", (dict,))
    post_parser = _require(arguments, "post_parser", (bool,), True)
    return _validated(show, post_parser=post_parser)


def tool_translate(arguments: dict) -> dict:
    show = _require(arguments, "show", (dict,))
    target = _require(arguments, "target", (str,))
    return translate(show, target)


def tool_horseshoe(arguments: dict) -> dict:
    show = _require(arguments, "show", (dict,))
    document = horseshoe(
        show,
        center_x=float(_require(arguments, "center_x", (int, float), 0.0)),
        center_y=float(_require(arguments, "center_y", (int, float), 0.0)),
        radius=float(_require(arguments, "radius", (int, float), 5.0)),
        start_deg=float(_require(arguments, "start_deg", (int, float), 180.0)),
        end_deg=float(_require(arguments, "end_deg", (int, float), 0.0)),
        apply_offsets=_require(arguments, "apply_offsets", (bool,), True),
    )
    return _validated(document, post_parser=False)


def tool_adapt(arguments: dict) -> dict:
    show = _require(arguments, "show", (dict,))
    matrix = _require(arguments, "matrix", (dict,), {})
    return _validated(adapt(show, matrix), post_parser=False)


def tool_fingerprint(arguments: dict) -> dict:
    frames = arguments.get("frames", arguments.get("channels"))
    if frames is None:
        raise ToolError("Falta 'frames' (lista de fotogramas DMX)")
    if not isinstance(frames, (list, tuple)):
        raise ToolError("'frames' debe ser una lista")
    return fingerprint(frames)


def tool_style_profile(arguments: dict) -> dict:
    show = _require(arguments, "show", (dict,))
    return style_profile(show)


def _validate_ma3_command(command: str) -> None:
    verb = command.strip().split(" ", 1)[0].lower()
    if verb not in MA3_VERBS:
        raise ToolError(
            f"Verbo MA3 no permitido: {verb!r}. Permitidos: {sorted(MA3_VERBS)}"
        )


def tool_osc_send(arguments: dict) -> dict:
    ip = _require(arguments, "ip", (str,))
    port = _require(arguments, "port", (int,), 8000)
    address = _require(arguments, "address", (str,))
    args = _require(arguments, "args", (list,), [])
    dry_run = _require(arguments, "dry_run", (bool,), True)

    if not address.startswith(ALLOWED_ADDRESS_PREFIXES):
        raise ToolError(
            f"Dirección no permitida: {address!r}. Prefijos válidos: {ALLOWED_ADDRESS_PREFIXES}"
        )
    if any(not isinstance(arg, (str, int, float)) for arg in args):
        raise ToolError("Los argumentos OSC deben ser str, int o float")
    if address.startswith(("/gma3/", "/grandMA3/")):
        for arg in args:
            if isinstance(arg, str):
                _validate_ma3_command(arg)

    info = send_message(ip, port, address, args, dry_run=dry_run)
    _record(address, args)
    return info


def tool_lua_generate(arguments: dict) -> dict:
    show = _require(arguments, "show", (dict,))
    name = _require(arguments, "macro_name", (str,))
    if not MACRO_NAME.match(name):
        raise ToolError("macro_name sólo admite [A-Za-z0-9_-] y hasta 64 caracteres")

    script = lua_script(show, name)
    GENERATED_DIR.mkdir(exist_ok=True)
    target = (GENERATED_DIR / f"{name}.lua").resolve()
    target.write_text(script, encoding="utf-8", newline="\n")
    return {
        "path": str(target.relative_to(REPO_ROOT)),
        "bytes": len(script.encode("utf-8")),
        "script": script,
        "note": "Escrito en generated/ del workspace. NO se copia al runtime de MA3 "
                "ni se ejecuta: la carga es una decisión manual del operador.",
    }


TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "show.parse_ma3",
        "description": "Convierte un export XML de grandMA3 en unified_show-1.0.0.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ruta relativa al repo"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "handler": tool_parse_ma3,
    },
    {
        "name": "show.parse_ma3_text",
        "description": "Igual que show.parse_ma3 pero desde XML en línea.",
        "inputSchema": {
            "type": "object",
            "properties": {"xml": {"type": "string"}},
            "required": ["xml"],
            "additionalProperties": False,
        },
        "handler": tool_parse_ma3_text,
    },
    {
        "name": "show.parse_chamsys",
        "description": "Importa un export CSV de ChamSys MagicQ a unified_show-1.0.0.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "csv": {"type": "string"}},
            "additionalProperties": False,
        },
        "handler": tool_parse_chamsys,
    },
    {
        "name": "show.validate",
        "description": "Valida reglas de negocio sobre un documento del contrato.",
        "inputSchema": {
            "type": "object",
            "properties": {"show": {"type": "object"}, "post_parser": {"type": "boolean"}},
            "required": ["show"],
            "additionalProperties": False,
        },
        "handler": tool_validate,
    },
    {
        "name": "show.translate",
        "description": "Traduce el show a comandos nativos de grandMA3 o ChamSys.",
        "inputSchema": {
            "type": "object",
            "properties": {"show": {"type": "object"}, "target": {"type": "string", "enum": ["grandMA3", "ChamSys"]}},
            "required": ["show", "target"],
            "additionalProperties": False,
        },
        "handler": tool_translate,
    },
    {
        "name": "layout.horseshoe",
        "description": "Reparte el rig en herradura y recalcula bearing y Pan hacia el centro.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "show": {"type": "object"},
                "center_x": {"type": "number"},
                "center_y": {"type": "number"},
                "radius": {"type": "number"},
                "start_deg": {"type": "number"},
                "end_deg": {"type": "number"},
                "apply_offsets": {"type": "boolean"},
            },
            "required": ["show"],
            "additionalProperties": False,
        },
        "handler": tool_horseshoe,
    },
    {
        "name": "geometry.adapt",
        "description": "Aplica escala/rotación/traslación afín a las posiciones del rig.",
        "inputSchema": {
            "type": "object",
            "properties": {"show": {"type": "object"}, "matrix": {"type": "object"}},
            "required": ["show"],
            "additionalProperties": False,
        },
        "handler": tool_adapt,
    },
    {
        "name": "fixture.fingerprint",
        "description": "Deduce roles de canal y modelo probable desde fotogramas DMX.",
        "inputSchema": {
            "type": "object",
            "properties": {"frames": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}},
            "required": ["frames"],
            "additionalProperties": False,
        },
        "handler": tool_fingerprint,
    },
    {
        "name": "rig.style_profile",
        "description": "Huella estilística determinista del rig (densidad, color, timing).",
        "inputSchema": {
            "type": "object",
            "properties": {"show": {"type": "object"}},
            "required": ["show"],
            "additionalProperties": False,
        },
        "handler": tool_style_profile,
    },
    {
        "name": "osc.send",
        "description": "Envía (o simula) un comando OSC a la consola. dry_run=true por defecto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string"},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "address": {"type": "string"},
                "args": {"type": "array"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["ip", "address"],
            "additionalProperties": False,
        },
        "handler": tool_osc_send,
    },
    {
        "name": "lua.generate",
        "description": "Genera un plugin Lua para MA3 a partir del show, en generated/.",
        "inputSchema": {
            "type": "object",
            "properties": {"show": {"type": "object"}, "macro_name": {"type": "string"}},
            "required": ["show", "macro_name"],
            "additionalProperties": False,
        },
        "handler": tool_lua_generate,
    },
)

HANDLERS: dict[str, Callable[[dict], dict]] = {tool["name"]: tool["handler"] for tool in TOOLS}


def list_tools() -> list[dict]:
    """Vista pública (sin handlers) para ``tools/list``."""
    return [
        {key: tool[key] for key in ("name", "description", "inputSchema")}
        for tool in TOOLS
    ]


def call_tool(name: str, arguments: dict | None = None) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ToolError(f"Herramienta desconocida: {name!r}", code=-32601)
    arguments = arguments or {}
    if not isinstance(arguments, dict):
        raise ToolError("'arguments' debe ser un objeto")
    try:
        result = handler(arguments)
    except ToolError:
        raise
    except (ValueError, TypeError, OSError, KeyError) as exc:
        raise ToolError(f"{type(exc).__name__}: {exc}", code=-32603) from exc
    return {"ok": True, "tool": name, "result": result}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)
