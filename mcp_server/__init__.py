"""Servidor MCP (JSON-RPC 2.0 sobre stdio) del puente MA.

Expone las capacidades del core a un LLM sin darle acceso a DMX crudo: todo
pasa por el Command Line de la consola y todo envío de red es ``dry_run`` por
defecto. La decisión de "escribir de verdad" es explícita del operador.
"""

from mcp_server.server import PROTOCOL_VERSION, handle_message, run_stdio

__all__ = ["PROTOCOL_VERSION", "handle_message", "run_stdio"]
