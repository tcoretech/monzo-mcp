# Monzo MCP Server for Claude Code

Read-only Monzo banking integration for Claude Code. Query balances, view transactions, check pots, and analyze spending — all through natural conversation.

## Features

| Tool | Description |
|------|-------------|
| `monzo_whoami` | Verify authentication status |
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

### Option 1: uvx (recommended — no clone needed)

```bash
claude mcp add monzo -- uvx --from monzo-mcp monzo-mcp
```

Claude Code will prompt you for `MONZO_CLIENT_ID` and `MONZO_CLIENT_SECRET`.

On first use, the server opens your browser to log in to Monzo. Tokens are stored internally — you never touch them.

### Option 2: Claude Code Plugin (Marketplace)

```bash
/plugin marketplace add tcoretech/monzo-mcp
/plugin install monzo@tcoretech
```

### Option 3: pip install

```bash
pip install monzo-mcp
```

Then register in Claude Code:

```bash
claude mcp add monzo -- monzo-mcp
```

### Option 4: Clone

```bash
git clone https://github.com/tcoretech/monzo-mcp.git
cd monzo-mcp
pip install -e .
claude mcp add monzo -- python mcp-server/server.py
```

---

## Authentication

### How it works

You only provide **two things** — your OAuth client credentials:

| Env Var | Where to get it |
| ------- | --------------- |
| `MONZO_CLIENT_ID` | [developers.monzo.com](https://developers.monzo.com/) |
| `MONZO_CLIENT_SECRET` | Same page |

Everything else is handled automatically:

1. **First tool call** — server detects no tokens, opens your browser to Monzo login
2. **You log in** — Monzo redirects back to `localhost:3118/callback`
3. **Tokens stored** — saved to `~/.monzo-mcp/tokens.json` (never in env vars)
4. **Auto-refresh** — tokens are refreshed automatically on expiry
5. **Account auto-detected** — your primary account is found automatically

> **Important:** After browser login, open your Monzo app and approve the push notification (Strong Customer Authentication).

### Manual auth setup (optional)

If you prefer to authenticate before first use:

```bash
# Interactive — prompts for client ID/secret if not in env
monzo-mcp-auth

# Or from source
python mcp-server/setup_auth.py
```

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
│   ├── auth.py              # OAuth token management + auto-refresh
│   ├── setup_auth.py        # Interactive browser OAuth setup
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
