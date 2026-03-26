"""Monzo MCP Server — read-only banking tools for Claude Code.

Provides tools to check balances, list transactions, view pots,
and analyze spending patterns via the Monzo API.

Requires MONZO_CLIENT_ID and MONZO_CLIENT_SECRET.
Tokens are managed internally via an automatic OAuth loopback flow.
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

# Singletons — lazily created on first use
_token_manager: TokenManager | None = None
_client: MonzoClient | None = None


def _get_token_manager() -> TokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager


def _get_client() -> MonzoClient:
    global _client
    if _client is None:
        tm = _get_token_manager()
        _client = MonzoClient(tm)
    return _client


# Register the read-only banking tools with lazy client factory
register_tools(mcp, _get_client)


def main():
    """Entry point for the monzo-mcp command."""
    mcp.run()


if __name__ == "__main__":
    main()
