from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import httpx
import keyring

from .config import Settings


TOKEN_SERVICE = "bqe-core-ai-data-connector"
TOKEN_CHUNK_SIZE = 800
TOKEN_MAX_CHUNKS = 32


@dataclass(frozen=True)
class PendingAuthorization:
    authorization_url: str
    state: str
    code_verifier: str


@dataclass(frozen=True)
class TokenRecord:
    access_token: str
    endpoint: str
    expires_at: str
    scope: str
    token_type: str = "Bearer"

    @property
    def expired(self) -> bool:
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= expiry - timedelta(seconds=30)


class WindowsTokenStore:
    """Store the short-lived access token in the current user's OS credential vault."""

    def __init__(self, client_id: str):
        self.client_id = client_id

    def save(self, token: TokenRecord) -> None:
        value = json.dumps(asdict(token), separators=(",", ":"))
        chunks = [value[index : index + TOKEN_CHUNK_SIZE] for index in range(0, len(value), TOKEN_CHUNK_SIZE)]
        if not chunks or len(chunks) > TOKEN_MAX_CHUNKS:
            raise ValueError("BQE token record exceeds the bounded Windows credential storage limit")
        self.clear()
        for index, chunk in enumerate(chunks):
            keyring.set_password(TOKEN_SERVICE, f"{self.client_id}:chunk:{index}", chunk)
        keyring.set_password(
            TOKEN_SERVICE,
            self.client_id,
            json.dumps({"format": "chunked-v1", "chunks": len(chunks)}),
        )

    def load(self) -> TokenRecord | None:
        manifest = keyring.get_password(TOKEN_SERVICE, self.client_id)
        if not manifest:
            return None
        metadata = json.loads(manifest)
        if metadata.get("format") != "chunked-v1":
            raise ValueError("Unrecognized BQE credential format")
        count = int(metadata.get("chunks", 0))
        if not 1 <= count <= TOKEN_MAX_CHUNKS:
            raise ValueError("Invalid BQE credential chunk count")
        chunks = [
            keyring.get_password(TOKEN_SERVICE, f"{self.client_id}:chunk:{index}")
            for index in range(count)
        ]
        if any(chunk is None for chunk in chunks):
            raise ValueError("BQE credential is incomplete")
        return TokenRecord(**json.loads("".join(chunk or "" for chunk in chunks)))

    def clear(self) -> None:
        manifest = keyring.get_password(TOKEN_SERVICE, self.client_id)
        count = TOKEN_MAX_CHUNKS
        if manifest:
            try:
                metadata = json.loads(manifest)
                count = min(int(metadata.get("chunks", TOKEN_MAX_CHUNKS)), TOKEN_MAX_CHUNKS)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        for index in range(max(count, 0)):
            try:
                keyring.delete_password(TOKEN_SERVICE, f"{self.client_id}:chunk:{index}")
            except keyring.errors.PasswordDeleteError:
                pass
        try:
            keyring.delete_password(TOKEN_SERVICE, self.client_id)
        except keyring.errors.PasswordDeleteError:
            pass


def validate_api_endpoint(endpoint: str) -> str:
    """Accept only HTTPS endpoints hosted by BQE CORE without userinfo or custom ports."""
    parsed = urlparse(endpoint)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError("BQE API endpoint must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("BQE API endpoint must not contain user information")
    if parsed.port not in (None, 443):
        raise ValueError("BQE API endpoint must use the default HTTPS port")
    if not hostname.endswith(".bqecore.com"):
        raise ValueError("BQE API endpoint host is not in the approved bqecore.com domain")
    return endpoint.rstrip("/")


def token_record(payload: dict[str, Any]) -> TokenRecord:
    access_token = payload.get("access_token")
    endpoint = payload.get("endpoint")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("Token response did not contain an access_token")
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("Token response did not contain the company API endpoint")
    granted = str(payload.get("scope", ""))
    granted_scopes = set(granted.split())
    if "readwrite:core" in granted_scopes:
        raise ValueError("Refusing a token containing readwrite:core")
    if granted_scopes and "read:core" not in granted_scopes:
        raise ValueError("Token response did not grant read:core")
    if payload.get("refresh_token"):
        raise ValueError("Unexpected refresh token for Native App; refusing to persist it")
    expires_in = max(1, int(payload.get("expires_in", 3600)))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return TokenRecord(
        access_token=access_token,
        endpoint=validate_api_endpoint(endpoint),
        expires_at=expires_at.isoformat(),
        scope=granted or "read:core",
        token_type=str(payload.get("token_type", "Bearer")),
    )


class OAuthPKCE:
    """Native-app OAuth with PKCE, state validation, and a loopback callback."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def prepare(self) -> PendingAuthorization:
        if not self.settings.client_id:
            raise RuntimeError("Set BQE_CLIENT_ID locally before preparing authorization")
        if tuple(self.settings.scopes) != ("read:core",):
            raise ValueError("Native App authorization must request exactly read:core")
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(32)
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "scope": "read:core",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return PendingAuthorization(
            f"{self.settings.authority}/connect/authorize?{urlencode(params)}",
            state,
            verifier,
        )

    def login(self, *, timeout_seconds: int = 180) -> TokenRecord:
        self._require_live_auth()
        pending = self.prepare()
        callback = urlparse(self.settings.redirect_uri)
        if callback.scheme != "http" or callback.hostname != "127.0.0.1":
            raise ValueError("Native callback must use http://127.0.0.1")
        if not callback.port or callback.path != "/callback":
            raise ValueError("Native callback must include the registered port and /callback path")

        result: dict[str, str] = {}
        expected_path = callback.path

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != expected_path:
                    self.send_response(404)
                    self.end_headers()
                    return
                values = parse_qs(parsed.query)
                for name in ("code", "state", "error", "error_description"):
                    if values.get(name):
                        result[name] = values[name][0]
                body = (
                    b"Authorization received. You may close this tab and return to Codex."
                    if "code" in result
                    else b"Authorization was not completed. Return to Codex for details."
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                return

        try:
            server = HTTPServer(("127.0.0.1", callback.port), CallbackHandler)
        except OSError as exc:
            raise RuntimeError(f"Cannot listen on 127.0.0.1:{callback.port}: {exc}") from exc
        server.timeout = 1
        opened = webbrowser.open(pending.authorization_url, new=1, autoraise=True)
        if not opened:
            server.server_close()
            raise RuntimeError("Could not open the system browser")
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() < deadline and not result:
                server.handle_request()
        finally:
            server.server_close()
        if not result:
            raise TimeoutError("BQE authorization timed out without a callback")
        if result.get("error"):
            raise RuntimeError(
                f"BQE authorization failed: {result['error']} "
                f"({result.get('error_description', 'no description')})"
            )
        if not result.get("state") or not secrets.compare_digest(result["state"], pending.state):
            raise RuntimeError("OAuth state mismatch; authorization was rejected")
        if not result.get("code"):
            raise RuntimeError("OAuth callback did not contain an authorization code")
        record = token_record(self.exchange_code(result["code"], pending.code_verifier))
        WindowsTokenStore(self.settings.client_id or "").save(record)
        return record

    def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        """Token-server POST is OAuth infrastructure, not a business-data write."""
        self._require_live_auth()
        with httpx.Client(transport=self.transport, timeout=30) as client:
            response = client.post(
                f"{self.settings.authority}/connect/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.redirect_uri,
                    "client_id": self.settings.client_id,
                    "code_verifier": code_verifier,
                },
            )
            response.raise_for_status()
            return response.json()

    def _require_live_auth(self) -> None:
        if not self.settings.live:
            raise RuntimeError(
                "LIVE authentication is disabled. Set BQE_MODE=LIVE and "
                "BQE_ENABLE_LIVE=YES only after review and explicit approval."
            )
        if not self.settings.client_id:
            raise RuntimeError("BQE_CLIENT_ID is required for OAuth")
