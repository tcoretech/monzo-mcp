"""Interactive OAuth setup for Monzo MCP server.

Opens a browser for Monzo login, handles the OAuth callback,
and stores tokens internally. Only needs CLIENT_ID and CLIENT_SECRET.

Usage:
    python setup_auth.py
    # or after pip install:
    monzo-mcp-auth
"""

import os
import sys


def main():
    print("\n  Monzo MCP — OAuth Setup")
    print("  " + "=" * 30 + "\n")

    # Prompt for client credentials if not in env
    client_id = os.environ.get("MONZO_CLIENT_ID", "")
    client_secret = os.environ.get("MONZO_CLIENT_SECRET", "")

    if not client_id:
        client_id = input("Enter your Monzo Client ID (from developers.monzo.com): ").strip()
        os.environ["MONZO_CLIENT_ID"] = client_id

    if not client_secret:
        client_secret = input("Enter your Monzo Client Secret: ").strip()
        os.environ["MONZO_CLIENT_SECRET"] = client_secret

    if not client_id or not client_secret:
        print("\nError: Client ID and Secret are required.")
        print("Create them at https://developers.monzo.com/")
        sys.exit(1)

    print(f"\nIMPORTANT: Your Monzo OAuth client's redirect URL must be:")
    print(f"  http://localhost:3118/callback")
    print(f"\nUpdate it at https://developers.monzo.com/ if needed.\n")

    # Import here so env vars are set first
    try:
        from monzo_mcp.auth import TokenManager
    except ImportError:
        from auth import TokenManager

    token_manager = TokenManager()

    print("Opening your browser to log in to Monzo...")
    token_manager.run_oauth_flow()

    print("\n  Setup complete!")
    print("  " + "=" * 30)
    print(f"\n  Tokens stored in: ~/.monzo-mcp/tokens.json")
    if token_manager.account_id:
        print(f"  Account ID: {token_manager.account_id}")
    print(f"\n  IMPORTANT: Open your Monzo app and approve the push")
    print(f"  notification (SCA requirement).\n")


if __name__ == "__main__":
    main()
