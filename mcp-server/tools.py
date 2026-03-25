"""MCP tool definitions for Monzo API.

Each tool is a function decorated with @mcp.tool() that wraps
a MonzoClient method. Tool docstrings become the descriptions
that Claude sees.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastmcp import FastMCP

try:
    from monzo_mcp.monzo_client import MonzoClient
except ImportError:
    from monzo_client import MonzoClient


def register_tools(mcp: FastMCP, client_or_factory: MonzoClient | Callable[[], MonzoClient]) -> None:
    """Register all Monzo tools with the MCP server.

    Args:
        mcp: The FastMCP server instance.
        client_or_factory: Either a MonzoClient instance or a callable
            that returns one (for lazy initialization).
    """

    def _client() -> MonzoClient:
        if callable(client_or_factory) and not isinstance(client_or_factory, MonzoClient):
            return client_or_factory()
        return client_or_factory  # type: ignore

    @mcp.tool()
    async def monzo_whoami() -> dict[str, Any]:
        """Check if the Monzo API connection is working and authenticated.

        Returns the authenticated user ID, client ID, and whether the token
        is authenticated. Use this to verify setup before other operations.
        """
        return await _client().whoami()

    @mcp.tool()
    async def monzo_list_accounts() -> list[dict[str, Any]]:
        """List all Monzo accounts (current account, joint account, etc.).

        Returns account IDs, descriptions, types, and creation dates.
        Use this to discover available account IDs for other queries.
        """
        accounts = await _client().list_accounts()
        return [
            {
                "id": a["id"],
                "description": a.get("description", ""),
                "type": a.get("type", ""),
                "currency": a.get("currency", "GBP"),
                "closed": a.get("closed", False),
                "created": a.get("created", ""),
            }
            for a in accounts
        ]

    @mcp.tool()
    async def monzo_get_balance(account_id: str = "") -> dict[str, Any]:
        """Get the current balance for a Monzo account.

        Args:
            account_id: The account to check. Leave empty to use the default
                        account from configuration.

        Returns balance, total_balance, spend_today (all in minor units, e.g.
        pence for GBP), and currency code.
        """
        data = await _client().get_balance(account_id or None)
        return {
            "balance": data.get("balance", 0),
            "total_balance": data.get("total_balance", 0),
            "balance_including_flexible_savings": data.get(
                "balance_including_flexible_savings", 0
            ),
            "spend_today": data.get("spend_today", 0),
            "currency": data.get("currency", "GBP"),
            "local_currency": data.get("local_currency", ""),
            "local_spend": data.get("local_spend", []),
            "_note": "All amounts are in minor units (pence for GBP). Divide by 100 for pounds.",
        }

    @mcp.tool()
    async def monzo_list_transactions(
        since: str = "",
        before: str = "",
        limit: int = 50,
        account_id: str = "",
    ) -> list[dict[str, Any]]:
        """List recent transactions from a Monzo account.

        Args:
            since: ISO 8601 timestamp (e.g. '2025-01-01T00:00:00Z'). Only
                   returns transactions after this time.
            before: ISO 8601 timestamp. Only returns transactions before this time.
            limit: Maximum number of transactions to return (max 100, default 50).
            account_id: The account to query. Leave empty for default account.

        Returns a list of transactions with amount, merchant, category, and
        timestamps. Amounts are in minor units (pence). Negative amounts are
        debits (spending), positive are credits (income/refunds).

        Note: Due to Strong Customer Authentication (SCA), transactions older
        than 90 days may not be accessible unless you recently re-authenticated
        in the Monzo app.
        """
        transactions = await _client().list_transactions(
            account_id=account_id or None,
            since=since or None,
            before=before or None,
            limit=limit,
        )
        return [_format_transaction(t) for t in transactions]

    @mcp.tool()
    async def monzo_get_transaction(transaction_id: str) -> dict[str, Any]:
        """Get full details of a single transaction by its ID.

        Args:
            transaction_id: The transaction ID (starts with 'tx_').

        Returns complete transaction data including merchant details,
        notes, attachments, and metadata.
        """
        t = await _client().get_transaction(transaction_id)
        return _format_transaction(t, verbose=True)

    @mcp.tool()
    async def monzo_list_pots() -> list[dict[str, Any]]:
        """List all savings pots with their balances and goals.

        Returns pot names, balances, goal amounts, and whether they are
        locked or round-up pots. Only shows non-deleted pots.
        """
        pots = await _client().list_pots()
        return [
            {
                "id": p["id"],
                "name": p.get("name", ""),
                "balance": p.get("balance", 0),
                "currency": p.get("currency", "GBP"),
                "goal_amount": p.get("goal_amount"),
                "style": p.get("style", ""),
                "type": p.get("type", ""),
                "round_up": p.get("round_up", False),
                "locked": p.get("locked", False),
                "deleted": p.get("deleted", False),
                "created": p.get("created", ""),
                "updated": p.get("updated", ""),
                "_note": "Amounts in minor units (pence for GBP).",
            }
            for p in pots
            if not p.get("deleted", False)
        ]

    @mcp.tool()
    async def monzo_spending_summary(
        days: int = 30,
        account_id: str = "",
    ) -> dict[str, Any]:
        """Analyze spending patterns over a time period.

        Fetches transactions and aggregates them by category and merchant,
        computing totals and averages. This is a computed analysis, not a
        direct Monzo API endpoint.

        Args:
            days: Number of days to analyze (default 30, max 90 due to SCA).
            account_id: The account to analyze. Leave empty for default.

        Returns spending grouped by category and top merchants, with totals.
        """
        days = min(days, 90)
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Fetch all transactions in the period (paginate if needed)
        all_transactions: list[dict[str, Any]] = []
        batch_since = since
        while True:
            batch = await _client().list_transactions(
                account_id=account_id or None,
                since=batch_since,
                limit=100,
            )
            if not batch:
                break
            all_transactions.extend(batch)
            if len(batch) < 100:
                break
            # Use last transaction ID as cursor for next page
            batch_since = batch[-1]["id"]

        # Filter to spending only (negative amounts, exclude pot transfers)
        spending = [
            t for t in all_transactions
            if t.get("amount", 0) < 0
            and not t.get("metadata", {}).get("pot_id")
            and not t.get("scheme", "") == "uk_retail_pot"
        ]

        # Aggregate by category
        by_category: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "count": 0, "transactions": []}
        )
        for t in spending:
            cat = t.get("category", "general")
            amount = abs(t.get("amount", 0))
            by_category[cat]["total"] += amount
            by_category[cat]["count"] += 1

        # Aggregate by merchant
        by_merchant: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "count": 0}
        )
        for t in spending:
            merchant = _get_merchant_name(t)
            amount = abs(t.get("amount", 0))
            by_merchant[merchant]["total"] += amount
            by_merchant[merchant]["count"] += 1

        # Income
        income = [t for t in all_transactions if t.get("amount", 0) > 0]
        total_income = sum(t.get("amount", 0) for t in income)

        total_spent = sum(cat["total"] for cat in by_category.values())
        top_merchants = sorted(
            by_merchant.items(), key=lambda x: x[1]["total"], reverse=True
        )[:10]
        categories_sorted = sorted(
            by_category.items(), key=lambda x: x[1]["total"], reverse=True
        )

        return {
            "period": f"Last {days} days",
            "since": since,
            "total_transactions": len(all_transactions),
            "total_spent": total_spent,
            "total_income": total_income,
            "net": total_income - total_spent,
            "currency": "GBP",
            "by_category": {
                cat: {"total": data["total"], "count": data["count"]}
                for cat, data in categories_sorted
            },
            "top_merchants": [
                {"name": name, "total": data["total"], "count": data["count"]}
                for name, data in top_merchants
            ],
            "_note": "All amounts in minor units (pence). Divide by 100 for pounds.",
        }


def _format_transaction(t: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    """Format a transaction into a clean, readable dict."""
    result: dict[str, Any] = {
        "id": t.get("id", ""),
        "amount": t.get("amount", 0),
        "currency": t.get("currency", "GBP"),
        "description": t.get("description", ""),
        "category": t.get("category", ""),
        "merchant": _get_merchant_name(t),
        "created": t.get("created", ""),
        "settled": t.get("settled", ""),
        "notes": t.get("notes", ""),
        "is_load": t.get("is_load", False),
        "decline_reason": t.get("decline_reason", ""),
    }

    if verbose:
        merchant = t.get("merchant")
        if isinstance(merchant, dict):
            result["merchant_details"] = {
                "id": merchant.get("id", ""),
                "name": merchant.get("name", ""),
                "category": merchant.get("category", ""),
                "logo": merchant.get("logo", ""),
                "address": merchant.get("address", {}),
                "online": merchant.get("online", False),
            }
        result["metadata"] = t.get("metadata", {})
        result["local_amount"] = t.get("local_amount")
        result["local_currency"] = t.get("local_currency")
        result["attachments"] = t.get("attachments", [])

    result["_note"] = "Amount in minor units (pence). Negative = debit, positive = credit."
    return result


def _get_merchant_name(t: dict[str, Any]) -> str:
    """Extract merchant name from a transaction."""
    merchant = t.get("merchant")
    if isinstance(merchant, dict):
        return merchant.get("name", t.get("description", "Unknown"))
    if isinstance(merchant, str) and merchant:
        return merchant
    return t.get("description", "Unknown")
