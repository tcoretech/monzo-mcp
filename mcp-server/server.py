"""Monzo MCP Server — read-only banking tools for Claude Code.

Provides tools to check balances, list transactions, view pots,
and analyze spending patterns via the Monzo API.

Only requires MONZO_CLIENT_ID and MONZO_CLIENT_SECRET as env vars.
Tokens are managed internally via OAuth browser flow.

Usage:
    python server.py
    # or after pip install:
    monzo-mcp
"""

import logging
import sys

from fastmcp import FastMCP

try:
    from monzo_mcp.auth import TokenManager
    from monzo_mcp.monzo_client import MonzoClient
    from monzo_mcp.tools import register_tools
except ImportError:
    from auth import TokenManager
    from monzo_client import MonzoClient
    from tools import register_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)

mcp = FastMCP("Monzo")

# Lazy init — only create client when tools are actually called
_client: MonzoClient | None = None


def _get_client() -> MonzoClient:
    global _client
    if _client is None:
        token_manager = TokenManager()
        # If no stored tokens, run OAuth flow automatically
        if not token_manager.is_authenticated:
            token_manager.run_oauth_flow()
        _client = MonzoClient(token_manager)
    return _client


# Register tools with lazy client
register_tools(mcp, _get_client)


def main():
    """Entry point for the monzo-mcp command."""
    mcp.run()


if __name__ == "__main__":
    main()
