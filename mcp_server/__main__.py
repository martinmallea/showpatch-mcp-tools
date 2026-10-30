"""Entrypoint: ``python -m mcp_server``."""

from mcp_server.server import run_stdio

if __name__ == "__main__":
    raise SystemExit(run_stdio())
