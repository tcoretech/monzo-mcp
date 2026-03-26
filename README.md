# Monzo MCP Server for Claude Code

Read-only Monzo banking integration for Claude Code. Query balances, view transactions, check pots, and analyze spending — all through natural conversation.

## Features

| Tool | Description |
|------|-------------|
| `monzo_is_authenticated` | Verify authentication status (live ping) |
| `monzo_list_accounts` | List all accounts (current, joint, flex) |
| `monzo_get_balance` | Current balance and today's spending |
| `monzo_list_transactions` | Transaction history with merchant details |
| `monzo_get_transaction` | Full detail on a single transaction |
| `monzo_list_pots` | All pots with balances and goals |
| `monzo_spending_summary` | Aggregated spending by category and merchant |

## Prerequisites

1. Python 3.10+
2. A [Monzo developer OAuth client](https://developers.monzo.com/) — **confidential** type
3. Set the redirect URL to `http://localhost:3118/callback`
4. Claude Code (CLI or VS Code extension)

> **Why do I need my own OAuth client?** Monzo restricts API access to personal use — there's no public app model. You create your own client at developers.monzo.com and only your credentials touch this server.

---

## Quick Start

### 1. Create an OAuth Client
Go to [developers.monzo.com](https://developers.monzo.com/) and create a **Confidential** client.
*   **Redirect URL:** `http://localhost:3118/callback`

### 2. Installation Options

#### Option 1: Claude Code Plugin (Marketplace)
```bash
/plugin marketplace add tcoretech/monzo-mcp
/plugin install monzo@tcoretech
```

#### Option 2: uvx (recommended — no clone needed)
```bash
claude mcp add monzo \
  -e MONZO_CLIENT_ID=your_client_id \
  -e MONZO_CLIENT_SECRET=your_client_secret \
  -- uvx --from monzo-mcp monzo-mcp
```

#### Option 3: pip install
```bash
pip install monzo-mcp
claude mcp add monzo \
  -e MONZO_CLIENT_ID=your_client_id \
  -e MONZO_CLIENT_SECRET=your_client_secret \
  -- monzo-mcp
```

#### Option 4: Clone & Run from Source
```bash
git clone https://github.com/tcoretech/monzo-mcp.git
cd monzo-mcp
pip install -e .
claude mcp add monzo \
  -e MONZO_CLIENT_ID=your_client_id \
  -e MONZO_CLIENT_SECRET=your_client_secret \
  -- python3 mcp-server/server.py
```

### 3. Generic MCP Configuration (Desktop/JSON)
For use with Claude Desktop or other MCP clients, add this to your configuration:

```json
{
  "mcpServers": {
    "monzo": {
      "command": "python3",
      "args": [
        "/absolute/path/to/monzo-mcp/mcp-server/server.py"
      ],
      "env": {
        "MONZO_CLIENT_ID": "YOUR_CLIENT_ID",
        "MONZO_CLIENT_SECRET": "YOUR_CLIENT_SECRET",
        "MONZO_REDIRECT_URI": "http://localhost:3118/callback"
      }
    }
  }
}
```

---

## Authentication (Seamless OAuth)

This server implements a **Seamless Loopback Flow**. You don't need to run a separate setup command.

1.  **Just-in-Time Auth:** When you first ask Claude about your Monzo account, the server will detect missing tokens and automatically open your browser to the Monzo login page.
2.  **Loopback Listener:** A temporary local server (defaulting to port 3118) catches the callback from Monzo and saves your tokens securely to `~/.monzo-mcp/tokens.json`.
3.  **WSL & Docker Support:** The server is environment-aware and will use PowerShell to bridge to your Windows host browser if running in WSL.
4.  **SCA (Strong Customer Authentication):** If Monzo requires an app approval, Claude will inform you. Simply tap "Approve" in your Monzo mobile app and tell Claude you've done so.

> **Note:** Tokens are stored with `0600` permissions (owner only). Access tokens are refreshed automatically.

### Where are tokens stored?

```text
~/.monzo-mcp/tokens.json    # access_token, refresh_token, account_id
```

This file is created automatically, permissions restricted to your user, and never needs manual editing. Delete it to force re-authentication.

---

## Usage Examples

Once connected, ask Claude things like:

- "What's my Monzo balance?"
- "Show my last 20 transactions"
- "How much did I spend on eating out this month?"
- "Give me a spending summary for the last 30 days"
- "What are my pot balances?"
- "Show transactions from Tesco last week"

---

## Architecture

```text
monzo-mcp/
├── .claude-plugin/          # Plugin metadata for marketplace
│   ├── plugin.json
│   └── marketplace.json
├── mcp-server/              # MCP server (Python)
│   ├── server.py            # FastMCP entry point (stdio)
│   ├── tools.py             # 7 read-only tool definitions
│   ├── monzo_client.py      # Async API client with retry
│   ├── auth.py              # OAuth token management, loopback listener, auto-refresh
│   └── .env.example
├── skills/monzo/
│   ├── SKILL.md             # Domain knowledge for Claude
│   └── monzo-api-reference.md
├── pyproject.toml           # Python packaging (pip/uvx)
├── LICENSE
└── README.md
```

**Credential flow:**

```text
User provides                 Server handles internally
┌──────────────────┐         ┌──────────────────────────┐
│ MONZO_CLIENT_ID  │──env──▶ │ OAuth browser flow       │
│ MONZO_CLIENT_SECRET│       │ Token exchange            │
└──────────────────┘         │ Token refresh             │
                             │ Account auto-detection    │
                             │ ~/.monzo-mcp/tokens.json  │
                             └──────────────────────────┘
```

**Security:**

- Read-only — no write operations, no fund transfers
- Credentials stored locally only, never transmitted beyond the Monzo API
- Token file restricted to user permissions (0600)
- Automatic token refresh on expiry
- Exponential backoff on rate limits

## Important Notes

- **90-day limit:** Due to Monzo's Strong Customer Authentication (SCA), transaction history is limited to 90 days unless you re-authenticate within 5 minutes in the Monzo app.
- **Personal use only:** The Monzo API is restricted to personal use — Monzo does not allow public applications.
- **Rate limits:** Monzo enforces rate limits. The client handles retries automatically.
- **Amounts:** All API amounts are in minor units (pence for GBP). Claude converts to pounds.

## License

MIT
