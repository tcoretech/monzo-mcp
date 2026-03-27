"""Token management for Monzo API authentication.

Reads MONZO_CLIENT_ID and MONZO_CLIENT_SECRET from:
  1. ~/.monzo-mcp/config.json (preferred — written by plugin setup)
  2. Environment variables (fallback — for manual MCP installs)
MONZO_REDIRECT_URI is optional (defaults to http://localhost:3118/callback).
All tokens (access, refresh) and account ID are obtained via OAuth
and stored internally in ~/.monzo-mcp/tokens.json.
"""

import html
import json
import logging
import os
import secrets
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

# Internal storage directory
TOKEN_DIR = Path.home() / ".monzo-mcp"
TOKEN_FILE = TOKEN_DIR / "tokens.json"
CONFIG_FILE = TOKEN_DIR / "config.json"


def _load_client_credentials() -> tuple[str, str]:
    """Load client_id and client_secret from config file or env vars."""
    # 1. Try config file (written by plugin setup flow)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            cid = data.get("client_id", "")
            csec = data.get("client_secret", "")
            if cid and csec:
                return cid, csec
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config file: %s", e)

    # 2. Fall back to env vars (manual MCP installs)
    return (
        os.environ.get("MONZO_CLIENT_ID", ""),
        os.environ.get("MONZO_CLIENT_SECRET", ""),
    )


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


def _is_remote_or_headless() -> bool:
    """Detect environments where the loopback listener likely won't receive the callback."""
    if os.environ.get("SSH_CLIENT") or os.environ.get("SSH_CONNECTION"):
        return True
    if os.path.exists("/.dockerenv"):
        return True
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        if os.name != "nt":  # Not Windows
            return True
    return _is_wsl()

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

_SUCCESS_PAGE = b"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Monzo MCP</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;min-height:100vh;
display:flex;align-items:center;justify-content:center;background:#0f0f0f;color:#e8e8e8}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:16px;padding:48px;
max-width:440px;text-align:center}
.check{width:64px;height:64px;margin:0 auto 24px;border-radius:50%;
background:#00d4aa20;display:flex;align-items:center;justify-content:center}
.check svg{width:32px;height:32px;color:#00d4aa}
h1{font-size:20px;font-weight:600;margin-bottom:8px}
.sub{color:#888;font-size:14px;margin-bottom:32px}
.sca{background:#1e1e2e;border:1px solid #333;border-radius:12px;padding:20px;text-align:left}
.sca-title{font-size:13px;font-weight:600;color:#f0c040;margin-bottom:8px;
display:flex;align-items:center;gap:8px}
.sca-body{font-size:13px;color:#aaa;line-height:1.5}
.sca-body strong{color:#e8e8e8}
</style></head><body><div class="card">
<div class="check" role="img" aria-label="Success"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
<polyline points="20 6 9 17 4 12"/></svg></div>
<h1>Connected to Monzo</h1>
<p class="sub">You can close this tab and return to your chat.</p>
<div class="sca"><div class="sca-title">\xf0\x9f\x94\x90 Check your phone</div>
<div class="sca-body">Open the <strong>Monzo app</strong> and tap
<strong>Approve</strong> on the push notification to complete
Strong Customer Authentication (SCA). Until you approve,
some API calls may be restricted.</div></div>
</div></body></html>"""


def _error_page(error: str) -> bytes:
    safe_error = html.escape(error)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Monzo MCP</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;min-height:100vh;
display:flex;align-items:center;justify-content:center;background:#0f0f0f;color:#e8e8e8}}
.card{{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:16px;padding:48px;
max-width:440px;text-align:center}}
.icon{{font-size:48px;margin-bottom:24px}}
h1{{font-size:20px;font-weight:600;margin-bottom:12px;color:#ff6b6b}}
.detail{{color:#888;font-size:13px;background:#111;border-radius:8px;
padding:12px;margin-top:16px;word-break:break-all;text-align:left}}
</style></head><body><div class="card">
<div class="icon" role="img" aria-label="Error">&#x26A0;&#xFE0F;</div>
<h1>Authentication Failed</h1>
<p style="color:#aaa;font-size:14px">Something went wrong during the Monzo login.</p>
<div class="detail">{safe_error}</div>
</div></body></html>""".encode("utf-8")


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
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            try:
                full_path = f"http://localhost:{port}{self.path}"
                token_manager.exchange_from_callback_url(full_path)
                self.wfile.write(_SUCCESS_PAGE)
            except Exception as e:
                self.wfile.write(_error_page(str(e)))
            
            # Stop the server after a short delay
            def shutdown_server():
                time.sleep(1)
                if _loopback_server:
                    _loopback_server.shutdown()
            threading.Thread(target=shutdown_server, daemon=True).start()

    try:
        _loopback_server = HTTPServer(("127.0.0.1", port), CallbackHandler)
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

    remote = _is_remote_or_headless()

    fallback_note = (
        "\n\nNOTE: If the redirect page shows a connection error after you "
        "log in (common in WSL, Docker, SSH, or remote environments), copy "
        "the FULL URL from the browser address bar and pass it to the "
        "monzo_complete_auth tool to finish authentication."
    )

    if remote:
        return (
            "Authentication required. Copy this link into a browser:\n\n"
            f"{auth_url}\n\n"
            "After logging in to Monzo, your browser will redirect to a "
            "localhost URL. Since the loopback listener may not be reachable "
            "from your local browser, copy the FULL URL from the browser "
            "address bar (starts with http://localhost:3118/callback?code=...) "
            "and pass it to the monzo_complete_auth tool."
        )

    return (
        "Authentication required. A browser window has been opened.\n"
        "If it didn't open automatically, copy this link:\n\n"
        f"{auth_url}\n\n"
        "Waiting for you to complete the login... (Timeout in 5 minutes)"
        f"{fallback_note}"
    )


class TokenManager:
    """Manages Monzo OAuth tokens with internal storage and auto-refresh.

    Only MONZO_CLIENT_ID and MONZO_CLIENT_SECRET are needed as env vars.
    Tokens are obtained via OAuth and stored in ~/.monzo-mcp/tokens.json,
    refreshed automatically on 401.
    """

    def __init__(self):
        self._client_id, self._client_secret = _load_client_credentials()
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._account_id: str = ""
        self._oauth_state: str = ""

        if not self._client_id or not self._client_secret:
            raise AuthError(
                "Monzo OAuth credentials not found. Either:\n"
                "  1. Create ~/.monzo-mcp/config.json with client_id and client_secret\n"
                "  2. Set MONZO_CLIENT_ID and MONZO_CLIENT_SECRET environment variables\n"
                "Get credentials at https://developers.monzo.com/"
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
        self._oauth_state = secrets.token_urlsafe(32)
        params = urllib.parse.urlencode({
            "client_id": self._client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": self._oauth_state,
        })
        return f"{MONZO_AUTH_URL}?{params}"

    # --- OAuth Code Exchange ---

    def exchange_from_callback_url(self, callback_url: str) -> None:
        """Extract auth code from a callback URL and exchange for tokens."""
        parsed = urllib.parse.urlparse(callback_url)
        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            raise AuthError(f"OAuth error: {params['error'][0]}")

        returned_state = params.get("state", [None])[0]
        if self._oauth_state and returned_state != self._oauth_state:
            raise AuthError("OAuth state mismatch — possible CSRF. Please retry authentication.")

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
        except Exception as e:
            logger.warning("Failed to detect account ID: %s", e)

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
