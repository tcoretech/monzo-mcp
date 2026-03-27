#!/bin/bash
# SessionStart hook: check if Monzo OAuth tokens exist.
# If missing, inform the user that authentication will be handled
# automatically when they first use a Monzo tool.
set -euo pipefail

TOKEN_FILE="$HOME/.monzo-mcp/tokens.json"

if [ ! -f "$TOKEN_FILE" ]; then
  cat <<'EOF'
Monzo MCP is installed but not yet authenticated. When you first use a Monzo tool, a browser window will open automatically for Monzo login. After logging in, approve the push notification in your Monzo app (SCA requirement).
EOF
fi
