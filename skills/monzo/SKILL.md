---
name: monzo
description: Use when querying Monzo bank account data, analyzing personal spending patterns, viewing pots and balances, or troubleshooting Monzo API authentication issues
---

# Monzo Banking Integration

Read-only access to Monzo bank data via MCP server. Dual-layer: MCP tools handle API calls, this skill provides domain knowledge.

## Available Tools

| Tool | What it does |
|------|-------------|
| `monzo_is_authenticated` | Verify auth status (live ping to Monzo API) |
| `monzo_list_accounts` | List all accounts (current, joint, flex) |
| `monzo_get_balance` | Balance, total balance, and today's spending |
| `monzo_list_transactions` | Recent transactions with merchant details |
| `monzo_get_transaction` | Full detail on a single transaction |
| `monzo_list_pots` | All pots with balances and goals |
| `monzo_spending_summary` | Aggregated spending by category and merchant |

## Key Constraints

**Strong Customer Authentication (SCA):** After re-authenticating in the Monzo app, full transaction history is available for 5 minutes. After that, only the last 90 days are accessible. If the user asks for older data, explain this limitation.

**Amounts:** All amounts from the API are in **minor units** (pence for GBP). Divide by 100 and format as pounds (e.g., `amount: -4599` → `-£45.99`). Negative = spending, positive = income/refund.

**Rate limits:** Monzo enforces rate limits (HTTP 429). The client handles retries automatically, but avoid making many rapid sequential calls. Prefer `monzo_spending_summary` over fetching transactions one-by-one.

## Spending Analysis Patterns

When asked about spending:
1. Start with `monzo_spending_summary` — it aggregates by category and merchant in one call
2. Use `monzo_list_transactions` with `since`/`before` for specific date ranges
3. Present amounts in pounds, grouped meaningfully (by category, merchant, or time)

**Categories** Monzo uses: `groceries`, `eating_out`, `entertainment`, `transport`, `shopping`, `bills`, `general`, `expenses`, `cash`, `holidays`, `personal_care`, `family`, `charity`, `finances`.

## Common Gotchas

- Always verify auth works with `monzo_is_authenticated` if other calls fail — it returns `needs_login`, `waiting_for_sca`, or `authenticated`
- If a tool returns `waiting_for_sca`, stop and tell the user to approve the notification in their Monzo app before retrying
- The `since` parameter on transactions can be a timestamp OR a transaction ID
- Pot transfers show as transactions but should be excluded from spending analysis (the `monzo_spending_summary` tool handles this)
- Max 100 transactions per API call — `monzo_spending_summary` paginates automatically
- Account ID defaults to the configured one; override with `account_id` param if querying joint/flex accounts
