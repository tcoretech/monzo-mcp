#!/bin/bash
# SessionStart hook: check Monzo plugin configuration state.
# Outputs context for Claude about what setup is needed.
set -euo pipefail

CONFIG_FILE="$HOME/.monzo-mcp/config.json"
TOKEN_FILE="$HOME/.monzo-mcp/tokens.json"

if [ ! -f "$CONFIG_FILE" ]; then
  cat <<'EOF'
MONZO_SETUP_REQUIRED: The Monzo MCP server needs OAuth credentials before it can connect.

You MUST do the following immediately:
1. Tell the user: "The Monzo plugin needs your OAuth credentials to connect. You can create these at https://developers.monzo.com — create a **Confidential** client with redirect URL `http://localhost:3118/callback`."
2. Ask the user for their **Client ID** (starts with `oauth2client_`)
3. Ask the user for their **Client Secret** (starts with `mnzconf.`)
4. Once you have both, create the config file by running:
   mkdir -p ~/.monzo-mcp && cat > ~/.monzo-mcp/config.json << CONF
   {
     "client_id": "THE_CLIENT_ID",
     "client_secret": "THE_CLIENT_SECRET"
   }
   CONF
   chmod 600 ~/.monzo-mcp/config.json
5. Tell the user to restart Claude Code so the MCP server can connect with the new credentials.

Do NOT try to use any Monzo tools until this setup is complete.
EOF
  exit 0
fi

if [ ! -f "$TOKEN_FILE" ]; then
  cat <<'EOF'
Monzo MCP credentials are configured but not yet authenticated. When you first use a Monzo tool, a browser window will open automatically for Monzo login. After logging in, approve the push notification in your Monzo app (SCA requirement).
EOF
fi
