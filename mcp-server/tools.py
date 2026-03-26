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
    from monzo_mcp.auth import NeedsAuthError
    from monzo_mcp.monzo_client import MonzoClient, MonzoSCAError
except ImportError:
    from auth import NeedsAuthError
    from monzo_client import MonzoClient, MonzoSCAError


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

    async def _handle_api_call(coro):
        try:
            return await coro
        except NeedsAuthError as e:
            return {
                "status": "needs_login",
                "message": e.message
            }
        except MonzoSCAError as e:
            return {
                "status": "waiting_for_sca",
                "message": (
                    "Strong Customer Authentication (SCA) required. "
                    "You MUST stop execution, inform the user to approve the "
                    "notification in their Monzo mobile app, and wait for "
                    "their confirmation before trying again."
                )
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def monzo_is_authenticated() -> dict[str, Any]:
        """Check if the Monzo API connection is working and authenticated.

        This tool performs a live 'ping' to Monzo's servers. 
        It will return:
        - 'Authenticated' if everything is working.
        - 'Needs Login' if OAuth tokens are missing or expired.
        - 'Waiting for SCA' if Monzo requires an app approval.
        
        If the response indicates SCA is required, you MUST stop execution, 
        inform the user to approve the notification in their Monzo mobile app, 
        and wait for their confirmation.
        """
        try:
            client = _client()
            await client.whoami()
            return {"status": "authenticated", "message": "Connected to Monzo API."}
        except NeedsAuthError as e:
            return {"status": "needs_login", "message": e.message}
        except MonzoSCAError:
            return {
                "status": "waiting_for_sca", 
                "message": "SCA required. Please approve the notification in your Monzo app."
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def monzo_list_accounts() -> Any:
        """List all Monzo accounts (current account, joint account, etc.).

        Returns account IDs, descriptions, types, and creation dates.
        Use this to discover available account IDs for other queries.
        
        If 'needs_login' is returned, follow the instructions in the message.
        If 'waiting_for_sca' is returned, tell the user to check their phone.
        """
        return await _handle_api_call(_client().list_accounts())

    @mcp.tool()
    async def monzo_get_balance(account_id: str = "") -> Any:
        """Get the current balance for a Monzo account.

        Args:
            account_id: The account to check. Leave empty to use the default
                        account from configuration.

        Returns balance, total_balance, spend_today (all in minor units, e.g.
        pence for GBP), and currency code.
        
        If the response indicates SCA is required, you MUST stop execution, 
        inform the user to approve the notification in their Monzo mobile app, 
        and wait for their confirmation.
        """
        return await _handle_api_call(_client().get_balance(account_id or None))

    @mcp.tool()
    async def monzo_list_transactions(
        since: str = "",
        before: str = "",
        limit: int = 50,
        account_id: str = "",
    ) -> Any:
        """List recent transactions from a Monzo account.

        Args:
            since: ISO 8601 timestamp (e.g. '2025-01-01T00:00:00Z'). Only
                   returns transactions after this time.
            before: ISO 8601 timestamp. Only returns transactions before this time.
            limit: Maximum number of transactions to return (max 100, default 50).
            account_id: The account to query. Leave empty for default account.

        Note: Due to Strong Customer Authentication (SCA), transactions older
        than 90 days may not be accessible unless you recently re-authenticated
        in the Monzo app.
        
        If the response indicates SCA is required, you MUST stop execution, 
        inform the user to approve the notification in their Monzo mobile app, 
        and wait for their confirmation.
        """
        res = await _handle_api_call(_client().list_transactions(
            account_id=account_id or None,
            since=since or None,
            before=before or None,
            limit=limit,
        ))
        if isinstance(res, list):
            return [_format_transaction(t) for t in res]
        return res

    @mcp.tool()
    async def monzo_get_transaction(transaction_id: str) -> Any:
        """Get full details of a single transaction by its ID.

        Args:
            transaction_id: The transaction ID (starts with 'tx_').

        If the response indicates SCA is required, you MUST stop execution, 
        inform the user to approve the notification in their Monzo mobile app, 
        and wait for their confirmation.
        """
        res = await _handle_api_call(_client().get_transaction(transaction_id))
        if isinstance(res, dict) and "status" not in res:
            return _format_transaction(res, verbose=True)
        return res

    @mcp.tool()
    async def monzo_list_pots() -> Any:
        """List all savings pots with their balances and goals.

        If the response indicates SCA is required, you MUST stop execution, 
        inform the user to approve the notification in their Monzo mobile app, 
        and wait for their confirmation.
        """
        res = await _handle_api_call(_client().list_pots())
        if isinstance(res, list):
            return [
                {
                    "id": p["id"],
                    "name": p.get("name", ""),
                    "balance": p.get("balance", 0),
                    "currency": p.get("currency", "GBP"),
                    "goal_amount": p.get("goal_amount"),
                    "round_up": p.get("round_up", False),
                    "locked": p.get("locked", False),
                    "created": p.get("created", ""),
                    "_note": "Amounts in minor units (pence for GBP).",
                }
                for p in res
                if not p.get("deleted", False)
            ]
        return res

    @mcp.tool()
    async def monzo_spending_summary(
        days: int = 30,
        account_id: str = "",
    ) -> Any:
        """Analyze spending patterns over a time period.

        Args:
            days: Number of days to analyze (default 30, max 90 due to SCA).
            account_id: The account to analyze. Leave empty for default.

        If the response indicates SCA is required, you MUST stop execution,
        inform the user to approve the notification in their Monzo mobile app,
        and wait for their confirmation.
        """
        async def _do_summary() -> dict[str, Any]:
            capped_days = min(days, 90)
            since = (
                datetime.now(timezone.utc) - timedelta(days=capped_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            client = _client()
            all_transactions: list[dict[str, Any]] = []
            batch_since = since
            while True:
                batch = await client.list_transactions(
                    account_id=account_id or None,
                    since=batch_since,
                    limit=100,
                )
                if not batch:
                    break
                all_transactions.extend(batch)
                if len(batch) < 100:
                    break
                batch_since = batch[-1]["id"]

            return _build_summary(all_transactions, capped_days)

        return await _handle_api_call(_do_summary())

def _build_summary(all_transactions: list[dict[str, Any]], days: int) -> dict[str, Any]:
    """Aggregate transactions into a spending summary."""
    spending = [
        t for t in all_transactions
        if t.get("amount", 0) < 0
        and not t.get("metadata", {}).get("pot_id")
        and not t.get("scheme", "") == "uk_retail_pot"
    ]

    by_category: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "count": 0}
    )
    for t in spending:
        cat = t.get("category", "general")
        amount = abs(t.get("amount", 0))
        by_category[cat]["total"] += amount
        by_category[cat]["count"] += 1

    by_merchant: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "count": 0}
    )
    for t in spending:
        merchant = _get_merchant_name(t)
        amount = abs(t.get("amount", 0))
        by_merchant[merchant]["total"] += amount
        by_merchant[merchant]["count"] += 1

    total_spent = sum(cat["total"] for cat in by_category.values())
    top_merchants = sorted(
        by_merchant.items(), key=lambda x: x[1]["total"], reverse=True
    )[:10]

    return {
        "period": f"Last {days} days",
        "total_spent": total_spent,
        "currency": "GBP",
        "by_category": dict(by_category),
        "top_merchants": [
            {"name": name, "total": data["total"], "count": data["count"]}
            for name, data in top_merchants
        ],
        "_note": "All amounts in minor units (pence).",
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
        "notes": t.get("notes", ""),
    }

    if verbose:
        result["metadata"] = t.get("metadata", {})
        result["decline_reason"] = t.get("decline_reason", "")

    result["_note"] = "Amount in minor units (pence). Negative = debit, positive = credit."
    return result


def _get_merchant_name(t: dict[str, Any]) -> str:
    """Extract merchant name from a transaction."""
    merchant = t.get("merchant")
    if isinstance(merchant, dict):
        return merchant.get("name", t.get("description", "Unknown"))
    return t.get("description", "Unknown")
