"""Transporte stdio y despacho JSON-RPC 2.0 / MCP.

Regla de oro del protocolo: stdout es SÓLO JSON-RPC. Cualquier log va a stderr,
porque una línea de texto suelta rompe el parser del cliente MCP.
"""

from __future__ import annotations

import json
import sys
from typing import TextIO

from mcp_server.tools import ToolError, call_tool, dumps, list_tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "showpatch", "version": "1.0.0"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _error(request_id, code: int, message: str, data=None) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


def _result(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle_message(message, state: dict | None = None) -> dict | None:
    """Procesa un mensaje ya decodificado. Devuelve respuesta o None si es notificación."""
    state = state if state is not None else {}
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, "El mensaje debe ser un objeto JSON")

    request_id = message.get("id")
    is_notification = "id" not in message

    if message.get("jsonrpc") != "2.0":
        return _error(request_id, INVALID_REQUEST, "Se requiere jsonrpc: \"2.0\"")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        return _error(request_id, INVALID_REQUEST, "Falta 'method'")

    if method == "initialize":
        state["initialized"] = True
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )

    if method in ("notifications/initialized", "initialized"):
        state["initialized"] = True
        return None

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": list_tools()})

    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, INVALID_PARAMS, "'params' debe ser un objeto")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error(request_id, INVALID_PARAMS, "Falta 'params.name'")
        arguments = params.get("arguments") or {}
        try:
            envelope = call_tool(name, arguments)
        except ToolError as exc:
            return _error(request_id, exc.code, exc.message)
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": dumps(envelope)}],
                "isError": False,
            },
        )

    if method == "shutdown":
        state["shutdown"] = True
        return _result(request_id, {})

    if method == "exit":
        state["exit"] = True
        return None if is_notification else _result(request_id, {})

    return _error(request_id, METHOD_NOT_FOUND, f"Método no encontrado: {method}")


def run_stdio(stdin: TextIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    """Bucle principal del servidor. Devuelve el código de salida del proceso."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    state: dict = {}
    print(f"[mcp] showpatch {SERVER_INFO['version']} listo (stdio)", file=stderr, flush=True)

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _error(None, PARSE_ERROR, f"JSON inválido: {exc.msg}")
        else:
            try:
                response = handle_message(message, state)
            except Exception as exc:  # nunca dejar caer el servidor por un bug de una tool
                request_id = message.get("id") if isinstance(message, dict) else None
                response = _error(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
        if state.get("exit"):
            break

    return 0
