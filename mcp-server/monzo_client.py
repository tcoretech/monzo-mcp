"""Async HTTP client for the Monzo API.

Wraps all API calls with authentication, automatic token refresh on 401,
and exponential backoff on 429 rate limits.
"""

import asyncio
import logging
import random
from typing import Any

import httpx

try:
    from monzo_mcp.auth import AuthError, TokenManager
except ImportError:
    from auth import AuthError, TokenManager

logger = logging.getLogger(__name__)

MONZO_API_BASE = "https://api.monzo.com"

# Rate limit retry config
MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds
BACKOFF_MAX = 30.0  # seconds


class MonzoAPIError(Exception):
    """Raised for non-recoverable Monzo API errors."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Monzo API error {status_code}: {message}")


class MonzoSCAError(MonzoAPIError):
    """Raised when Strong Customer Authentication (SCA) is required."""

    def __init__(self, message: str):
        super().__init__(403, message)


class MonzoClient:
    """Async client for Monzo API with auth refresh and rate limit handling."""

    def __init__(self, token_manager: TokenManager):
        self._token_manager = token_manager
        self._client = httpx.AsyncClient(
            base_url=MONZO_API_BASE,
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def account_id(self) -> str:
        return self._token_manager.account_id

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request with retry logic.

        - On 401: attempt token refresh once, then retry.
        - On 403: raise MonzoSCAError (SCA required).
        - On 429: exponential backoff with jitter, up to MAX_RETRIES.
        - Other 4xx/5xx: raise MonzoAPIError.
        """
        headers = self._token_manager.get_headers()
        refreshed = False

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.request(
                    method, path, headers=headers, params=params, data=data
                )
            except httpx.RequestError as e:
                raise MonzoAPIError(0, f"Request failed: {e}") from e

            if response.status_code == 401 and not refreshed:
                logger.info("Got 401, attempting token refresh")
                await self._token_manager.refresh(self._client)
                headers = self._token_manager.get_headers()
                refreshed = True
                continue

            if response.status_code == 403:
                raise MonzoSCAError(
                    "Strong Customer Authentication (SCA) required. "
                    "Please approve the notification in your Monzo mobile app."
                )

            if response.status_code == 429 and attempt < MAX_RETRIES:
                delay = min(
                    BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1),
                    BACKOFF_MAX,
                )
                logger.warning("Rate limited (429), retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                body = response.text
                raise MonzoAPIError(response.status_code, body)

            return response.json()

        raise MonzoAPIError(429, "Rate limit exceeded after max retries")

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    # --- API Methods ---

    async def whoami(self) -> dict[str, Any]:
        """Check authentication status. GET /ping/whoami"""
        return await self.get("/ping/whoami")

    async def list_accounts(self) -> list[dict[str, Any]]:
        """List all accounts. GET /accounts"""
        data = await self.get("/accounts")
        return data.get("accounts", [])

    async def get_balance(self, account_id: str | None = None) -> dict[str, Any]:
        """Get balance for an account. GET /balance"""
        return await self.get("/balance", params={
            "account_id": account_id or self.account_id
        })

    async def list_transactions(
        self,
        account_id: str | None = None,
        since: str | None = None,
        before: str | None = None,
        limit: int = 100,
        expand_merchant: bool = True,
    ) -> list[dict[str, Any]]:
        """List transactions with optional filters. GET /transactions"""
        params: dict[str, Any] = {
            "account_id": account_id or self.account_id,
            "limit": min(limit, 100),
        }
        if expand_merchant:
            params["expand[]"] = "merchant"
        if since:
            params["since"] = since
        if before:
            params["before"] = before

        data = await self.get("/transactions", params=params)
        return data.get("transactions", [])

    async def get_transaction(
        self, transaction_id: str, expand_merchant: bool = True
    ) -> dict[str, Any]:
        """Get a single transaction. GET /transactions/{id}"""
        params: dict[str, Any] = {}
        if expand_merchant:
            params["expand[]"] = "merchant"
        data = await self.get(f"/transactions/{transaction_id}", params=params)
        return data.get("transaction", data)

    async def list_pots(self) -> list[dict[str, Any]]:
        """List all pots. GET /pots"""
        data = await self.get("/pots", params={
            "current_account_id": self.account_id
        })
        return data.get("pots", [])
