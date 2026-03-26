"""Token management for Monzo API authentication.

Requires MONZO_CLIENT_ID and MONZO_CLIENT_SECRET.
MONZO_REDIRECT_URI is optional (defaults to http://localhost:3118/callback).
All tokens (access, refresh) and account ID are obtained via OAuth
and stored internally in ~/.monzo-mcp/tokens.json.
"""

import json
import logging
import os
import urllib.parse
from pathlib import Path
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import subprocess
import time

import httpx

logger = logging.getLogger(__name__)

MONZO_AUTH_URL = "https://auth.monzo.com/"
MONZO_TOKEN_URL = "https://api.monzo.com/oauth2/token"
MONZO_API_BASE = "https://api.monzo.com"
REDIRECT_URI = os.environ.get("MONZO_REDIRECT_URI", "http://localhost:3118/callback")

# Internal token storage — user never touches this
TOKEN_DIR = Path.home() / ".monzo-mcp"
TOKEN_FILE = TOKEN_DIR / "tokens.json"


class AuthError(Exception):
    """Raised when authentication fails and cannot be recovered."""


class NeedsAuthError(AuthError):
    """Raised when OAuth is required. Triggers background flow."""

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(message or "Monzo authentication required.")


_loopback_running = False
_loopback_lock = threading.Lock()
_loopback_server = None

def _is_wsl() -> bool:
    try:
        if os.path.exists("/proc/sys/kernel/osrelease"):
            with open("/proc/sys/kernel/osrelease", "r") as f:
                return "microsoft" in f.read().lower()
    except Exception:
        pass
    return False

def _open_browser(url: str) -> None:
    if _is_wsl():
        try:
            # Use powershell.exe to open URL from WSL
            subprocess.run(["powershell.exe", "-Command", f"Start-Process '{url}'"], check=True, capture_output=True)
            return
        except Exception as e:
            logger.warning("Failed to open browser via powershell in WSL: %s", e)
    
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.warning("Failed to open browser: %s", e)

def trigger_background_auth_flow(token_manager: "TokenManager") -> str:
    global _loopback_running, _loopback_server
    
    with _loopback_lock:
        if _loopback_running:
            return "Authentication is already in progress. Please check your browser or terminal output."
        _loopback_running = True

    try:
        parsed_uri = urllib.parse.urlparse(REDIRECT_URI)
        port = parsed_uri.port or 3118
    except Exception:
        port = 3118

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            
            try:
                # Construct full URL for exchange
                full_path = f"http://localhost:{port}{self.path}"
                token_manager.exchange_from_callback_url(full_path)
                self.wfile.write(b"<html><body><h1>Authentication successful!</h1><p>You can close this tab and return to the chat.</p></body></html>")
            except Exception as e:
                self.wfile.write(f"<html><body><h1>Authentication failed</h1><p>{e}</p></body></html>".encode("utf-8"))
            
            # Stop the server after a short delay
            def shutdown_server():
                time.sleep(1)
                if _loopback_server:
                    _loopback_server.shutdown()
            threading.Thread(target=shutdown_server, daemon=True).start()

    try:
        _loopback_server = HTTPServer(("0.0.0.0", port), CallbackHandler)
    except Exception as e:
        with _loopback_lock:
            _loopback_running = False
            _loopback_server = None
        return f"Failed to start local listener on port {port}: {e}"

    def run_server():
        global _loopback_running, _loopback_server
        try:
            _loopback_server.serve_forever()
        finally:
            if _loopback_server:
                _loopback_server.server_close()
            with _loopback_lock:
                _loopback_running = False
                _loopback_server = None

    threading.Thread(target=run_server, daemon=True).start()

    # Timeout thread (5 minutes)
    def timeout_server():
        time.sleep(300)
        with _loopback_lock:
            if _loopback_running and _loopback_server:
                logger.info("Auth loopback server timed out after 5 minutes")
                _loopback_server.shutdown()

    threading.Thread(target=timeout_server, daemon=True).start()

    auth_url = token_manager.generate_auth_url()
    _open_browser(auth_url)

    wsl_note = ""
    if _is_wsl():
        wsl_note = (
            "\n\nNOTE (WSL detected): The automatic callback listener may not "
            "work in WSL due to network isolation. After logging in, if the "
            "browser shows a connection error on the redirect page, copy the "
            "FULL URL from the browser address bar and pass it to the "
            "monzo_complete_auth tool to finish authentication."
        )

    return (
        "Authentication required. A browser window has been opened.\n"
        "If it didn't open automatically, please click this link:\n\n"
        f"{auth_url}\n\n"
        "Waiting for you to complete the login... (Timeout in 5 minutes)"
        f"{wsl_note}"
    )


class TokenManager:
    """Manages Monzo OAuth tokens with internal storage and auto-refresh.

    Only MONZO_CLIENT_ID and MONZO_CLIENT_SECRET are needed as env vars.
    Tokens are obtained via OAuth and stored in ~/.monzo-mcp/tokens.json,
    refreshed automatically on 401.
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
            msg = trigger_background_auth_flow(self)
            raise NeedsAuthError(msg)
        return {"Authorization": f"Bearer {self._access_token}"}

    # --- OAuth URL Generation ---

    def generate_auth_url(self) -> str:
        """Generate the Monzo OAuth authorization URL."""
        params = urllib.parse.urlencode({
            "client_id": self._client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": "monzo_mcp",
        })
        return f"{MONZO_AUTH_URL}?{params}"

    # --- OAuth Code Exchange ---

    def exchange_from_callback_url(self, callback_url: str) -> None:
        """Extract auth code from a callback URL and exchange for tokens."""
        parsed = urllib.parse.urlparse(callback_url)
        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            raise AuthError(f"OAuth error: {params['error'][0]}")

        code = params.get("code", [None])[0]
        if not code:
            raise AuthError("No authorization code found in the URL.")

        self._exchange_code(code)
        self._detect_account_id()
        self._save_tokens()
        logger.info("Authentication completed successfully")

    # --- Token Storage ---

    def _load_stored_tokens(self) -> None:
        """Load tokens from internal storage (~/.monzo-mcp/tokens.json)."""
        if not TOKEN_FILE.exists():
            return

        try:
            data = json.loads(TOKEN_FILE.read_text())
            self._access_token = data.get("access_token", "")
            self._refresh_token = data.get("refresh_token", "")
            self._account_id = data.get("account_id", "")
        except (json.JSONDecodeError, OSError):
            pass

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
            try:
                os.chmod(TOKEN_FILE, 0o600)
            except OSError:
                pass
        except OSError as e:
            logger.error("Failed to save tokens: %s", e)

    # --- Token Exchange ---

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
                headers={"Authorization": f"Bearer {self._access_token}"},
                params={"account_type": "uk_retail"},
            )
            response.raise_for_status()
            accounts = response.json().get("accounts", [])
            for acc in accounts:
                if not acc.get("closed", False):
                    self._account_id = acc["id"]
                    return
        except Exception:
            pass

    # --- Token Refresh ---

    async def refresh(self, client: httpx.AsyncClient) -> None:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            msg = trigger_background_auth_flow(self)
            raise NeedsAuthError(msg)

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
            if e.response.status_code == 401:
                msg = trigger_background_auth_flow(self)
                raise NeedsAuthError(msg) from e
            raise AuthError(f"Token refresh failed: {e}") from e
        except httpx.RequestError as e:
            raise AuthError(f"Token refresh request failed: {e}") from e

        data = response.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)

        self._save_tokens()
