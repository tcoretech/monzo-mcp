#!/bin/bash
# SessionStart hook: check if Monzo OAuth tokens exist.
# Checks keychain first, then falls back to plaintext file.
set -euo pipefail

TOKEN_FILE="$HOME/.monzo-mcp/tokens.json"

# Check keychain for tokens
HAS_KEYRING_TOKENS=false
if command -v python3 &>/dev/null; then
  HAS_KEYRING_TOKENS=$(python3 -c "
try:
    import keyring
    t = keyring.get_password('monzo-mcp', 'tokens')
    print('true' if t else 'false')
except:
    print('false')
" 2>/dev/null || echo "false")
fi

if [ "$HAS_KEYRING_TOKENS" = "false" ] && [ ! -f "$TOKEN_FILE" ]; then
  cat <<'EOF'
Monzo MCP is installed but not yet authenticated. When you first use a Monzo tool, a browser window will open automatically for Monzo login. After logging in, approve the push notification in your Monzo app (SCA requirement).
EOF
fi
