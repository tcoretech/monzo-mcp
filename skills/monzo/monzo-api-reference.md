# Monzo API Reference

Base URL: `https://api.monzo.com`

Full docs: https://docs.monzo.com/

## Authentication

OAuth 2.0 with Bearer tokens. All requests require `Authorization: Bearer {access_token}`.

### Token Refresh

```
POST /oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
client_id={client_id}
client_secret={client_secret}
refresh_token={refresh_token}
```

Response: `{ "access_token": "...", "refresh_token": "...", "token_type": "Bearer", "expires_in": 21600 }`

### Strong Customer Authentication (SCA)

- After initial OAuth, user must approve access via Monzo app (push notification)
- Full transaction history: available for **5 minutes** after SCA approval
- After 5 minutes: only **90 days** of transactions accessible
- Re-authentication: user must re-approve in Monzo app

## Endpoints

### GET /ping/whoami

Verify authentication status.

Response:
```json
{
  "authenticated": true,
  "client_id": "oauth2client_...",
  "user_id": "user_..."
}
```

### GET /accounts

List accounts. Optional param: `account_type` (uk_retail, uk_retail_joint).

Response:
```json
{
  "accounts": [
    {
      "id": "acc_...",
      "description": "user_...",
      "type": "uk_retail",
      "currency": "GBP",
      "closed": false,
      "created": "2019-01-01T00:00:00Z"
    }
  ]
}
```

### GET /balance

Params: `account_id` (required)

Response:
```json
{
  "balance": 50000,
  "total_balance": 50000,
  "balance_including_flexible_savings": 75000,
  "currency": "GBP",
  "spend_today": -2500,
  "local_currency": "",
  "local_exchange_rate": 0,
  "local_spend": []
}
```

All amounts in minor units (pence). `balance: 50000` = £500.00.

### GET /transactions

Params:
- `account_id` (required)
- `since` — ISO 8601 timestamp or transaction ID
- `before` — ISO 8601 timestamp
- `limit` — max 100
- `expand[]` — set to `merchant` for full merchant details

Response:
```json
{
  "transactions": [
    {
      "id": "tx_...",
      "created": "2025-03-20T12:00:00Z",
      "description": "TESCO STORES",
      "amount": -4599,
      "currency": "GBP",
      "merchant": {
        "id": "merch_...",
        "name": "Tesco",
        "category": "groceries",
        "logo": "https://...",
        "address": { "short_formatted": "123 High St, London" },
        "online": false
      },
      "category": "groceries",
      "notes": "",
      "metadata": {},
      "settled": "2025-03-21T00:00:00Z",
      "is_load": false,
      "decline_reason": ""
    }
  ]
}
```

### GET /transactions/{id}

Same as above but single transaction. Supports `expand[]=merchant`.

### GET /pots

Params: `current_account_id` (required)

Response:
```json
{
  "pots": [
    {
      "id": "pot_...",
      "name": "Holiday Fund",
      "balance": 150000,
      "currency": "GBP",
      "goal_amount": 500000,
      "type": "default",
      "round_up": false,
      "locked": false,
      "deleted": false,
      "created": "2024-06-01T00:00:00Z",
      "updated": "2025-03-20T00:00:00Z",
      "style": "savings"
    }
  ]
}
```

## Monzo Transaction Categories

| Category | Description |
|----------|-------------|
| `general` | Uncategorized |
| `groceries` | Supermarkets, food shops |
| `eating_out` | Restaurants, cafes, takeaways |
| `entertainment` | Cinema, events, subscriptions |
| `transport` | Fuel, public transport, taxis, parking |
| `shopping` | Retail, online shopping |
| `bills` | Utilities, rent, regular payments |
| `expenses` | Work expenses |
| `cash` | ATM withdrawals |
| `holidays` | Travel and holiday spending |
| `personal_care` | Health, beauty, fitness |
| `family` | Childcare, family-related |
| `charity` | Charitable donations |
| `finances` | Savings, investments, transfers |

## Error Codes

| Code | Meaning |
|------|---------|
| 400 | Bad request — check parameters |
| 401 | Unauthorized — token expired or invalid |
| 403 | Forbidden — insufficient permissions or SCA required |
| 404 | Not found — invalid ID |
| 405 | Method not allowed |
| 429 | Rate limited — back off and retry |
| 500 | Internal server error — retry later |
