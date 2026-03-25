"""Token management for Monzo API authentication.

Only requires MONZO_CLIENT_ID and MONZO_CLIENT_SECRET as env vars.
All tokens (access, refresh) and account ID are obtained via OAuth
browser flow and stored internally in ~/.monzo-mcp/tokens.json.
"""

import http.server
import json
import logging
import os
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MONZO_AUTH_URL = "https://auth.monzo.com/"
MONZO_TOKEN_URL = "https://api.monzo.com/oauth2/token"
MONZO_API_BASE = "https://api.monzo.com"
CALLBACK_PORT = 3118
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"

# Internal token storage — user never touches this
TOKEN_DIR = Path.home() / ".monzo-mcp"
TOKEN_FILE = TOKEN_DIR / "tokens.json"


class AuthError(Exception):
    """Raised when authentication fails and cannot be recovered."""


class NeedsAuthError(AuthError):
    """Raised when OAuth browser flow is required."""

    def __init__(self):
        super().__init__(
            "Monzo authentication required. Run `monzo-mcp-auth` or "
            "`python setup_auth.py` to log in via your browser."
        )


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback."""

    auth_code: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            _OAuthCallbackHandler.error = params["error"][0]
            self._respond("Authentication failed. You can close this tab.")
            return

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self._respond(
                "Monzo authentication successful! "
                "You can close this tab and return to Claude Code."
            )
            return

        self.send_response(400)
        self.end_headers()

    def _respond(self, message: str):
        html = (
            f'<!DOCTYPE html><html><head><title>Monzo MCP</title>'
            f'<style>body{{font-family:system-ui;display:flex;justify-content:center;'
            f'align-items:center;height:100vh;margin:0;background:#1a1a2e;color:#e0e0e0}}'
            f'.card{{background:#16213e;padding:2rem;border-radius:12px;text-align:center}}'
            f'h2{{color:#00d4aa}}</style></head>'
            f'<body><div class="card"><h2>{message}</h2></div></body></html>'
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress request logging


class TokenManager:
    """Manages Monzo OAuth tokens with internal storage and auto-refresh.

    Only MONZO_CLIENT_ID and MONZO_CLIENT_SECRET are needed as env vars.
    Tokens are obtained via OAuth browser flow and stored in
    ~/.monzo-mcp/tokens.json, refreshed automatically on 401.
    """

    def __init__(self):
        self._client_id = os.environ.get("MONZO_CLIENT_ID", "")
        self._client_secret = os.environ.get("MONZO_CLIENT_SECRET", "")
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._account_id: str = ""

        if not self._client_id or not self._client_secret:
            raise AuthError(
                "MONZO_CLIENT_ID and MONZO_CLIENT_SECRET environment variables "
                "are required. Create an OAuth client at https://developers.monzo.com/ "
                "and pass these as env vars in your MCP config."
            )

        self._load_stored_tokens()

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def get_headers(self) -> dict[str, str]:
        """Return authorization headers for API requests."""
        if not self._access_token:
            raise NeedsAuthError()
        return {"Authorization": f"Bearer {self._access_token}"}

    # --- Token Storage ---

    def _load_stored_tokens(self) -> None:
        """Load tokens from internal storage (~/.monzo-mcp/tokens.json)."""
        if not TOKEN_FILE.exists():
            logger.info("No stored tokens found at %s", TOKEN_FILE)
            return

        try:
            data = json.loads(TOKEN_FILE.read_text())
            self._access_token = data.get("access_token", "")
            self._refresh_token = data.get("refresh_token", "")
            self._account_id = data.get("account_id", "")
            logger.info("Loaded stored tokens")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load stored tokens: %s", e)

    def _save_tokens(self) -> None:
        """Persist tokens to internal storage."""
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "account_id": self._account_id,
        }
        try:
            TOKEN_FILE.write_text(json.dumps(data, indent=2))
            # Restrict permissions on token file (best effort on Windows)
            try:
                TOKEN_FILE.chmod(0o600)
            except OSError:
                pass
            logger.info("Tokens saved to %s", TOKEN_FILE)
        except OSError as e:
            logger.error("Failed to save tokens: %s", e)

    # --- OAuth Browser Flow ---

    def run_oauth_flow(self) -> None:
        """Run the interactive OAuth browser flow.

        Opens the user's browser to Monzo login, handles the callback,
        exchanges the code for tokens, and stores them.
        """
        logger.info("Starting OAuth browser flow")

        # Reset callback handler state
        _OAuthCallbackHandler.auth_code = None
        _OAuthCallbackHandler.error = None

        # Start local callback server
        server = http.server.HTTPServer(
            ("localhost", CALLBACK_PORT), _OAuthCallbackHandler
        )
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        # Open browser to Monzo auth
        auth_params = urllib.parse.urlencode({
            "client_id": self._client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": "monzo_mcp",
        })
        auth_url = f"{MONZO_AUTH_URL}?{auth_params}"
        webbrowser.open(auth_url)
        logger.info("Opened browser for Monzo login")

        # Wait for callback (5 minute timeout)
        server_thread.join(timeout=300)
        server.server_close()

        if _OAuthCallbackHandler.error:
            raise AuthError(f"OAuth failed: {_OAuthCallbackHandler.error}")

        if not _OAuthCallbackHandler.auth_code:
            raise AuthError("OAuth timeout — no authorization received within 5 minutes")

        # Exchange code for tokens
        self._exchange_code(_OAuthCallbackHandler.auth_code)

        # Auto-detect account ID
        self._detect_account_id()

        # Save everything
        self._save_tokens()

        logger.info("OAuth flow completed successfully")

    def _exchange_code(self, code: str) -> None:
        """Exchange authorization code for access + refresh tokens."""
        response = httpx.post(
            MONZO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": REDIRECT_URI,
                "code": code,
            },
        )
        if response.status_code >= 400:
            raise AuthError(f"Token exchange failed: {response.text}")

        data = response.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", "")

    def _detect_account_id(self) -> None:
        """Fetch the primary account ID after authentication."""
        try:
            response = httpx.get(
                f"{MONZO_API_BASE}/accounts",
                headers=self.get_headers(),
                params={"account_type": "uk_retail"},
            )
            response.raise_for_status()
            accounts = response.json().get("accounts", [])
            for acc in accounts:
                if not acc.get("closed", False):
                    self._account_id = acc["id"]
                    logger.info("Auto-detected account ID: %s", self._account_id)
                    return
        except Exception as e:
            logger.warning("Could not auto-detect account ID: %s", e)

    # --- Token Refresh ---

    async def refresh(self, client: httpx.AsyncClient) -> None:
        """Refresh the access token using the refresh token.

        Called automatically by MonzoClient on 401 responses.
        """
        if not self._refresh_token:
            raise NeedsAuthError()

        logger.info("Refreshing access token")

        try:
            response = await client.post(
                MONZO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AuthError(
                f"Token refresh failed (HTTP {e.response.status_code}). "
                "Run `monzo-mcp-auth` to re-authenticate."
            ) from e
        except httpx.RequestError as e:
            raise AuthError(f"Token refresh request failed: {e}") from e

        data = response.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)

        self._save_tokens()
        logger.info("Token refreshed and saved")
