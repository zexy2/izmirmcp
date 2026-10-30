"""Stdio MCP entrypoint for desktop clients.

Run with: .venv/bin/python -m app.stdio
"""

from __future__ import annotations

from app.core.settings import get_settings
from app.mcp.registry import create_mcp_server


def main() -> None:
    server = create_mcp_server(get_settings())
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
