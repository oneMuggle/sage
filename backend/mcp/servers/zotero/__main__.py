"""Entry point for ``python -m backend.mcp.servers.zotero``.

Launched by the MCP pool as a stdio subprocess.
"""

import asyncio

from backend.mcp.servers.zotero.server import run_zotero_mcp_server

if __name__ == "__main__":
    asyncio.run(run_zotero_mcp_server())
