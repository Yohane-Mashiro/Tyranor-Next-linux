from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass

import requests

from .secrets import SecretStore
from .settings import Settings


AUTHORIZE_URL = "https://id.hikarinagi.org/oidc/auth"
TOKEN_URL = "https://id.hikarinagi.org/oidc/token"
SCOPES = "openid catalog:read catalog:full offline_access"


class HikarinagiError(RuntimeError):
    pass


@dataclass(slots=True)
class TokenState:
    access_token: str
    refresh_token: str
    expires_at: float
    last_error: str = ""


class HikarinagiAuth:
    def __init__(self, settings: Settings, secret_store: SecretStore | None = None):
        self.settings = settings
        self.secrets = secret_store or SecretStore()

    def token_state(self) -> TokenState:
        return TokenState(
            access_token=self.secrets.get("hikarinagi_access_token", ""),
            refresh_token=self.secrets.get("hikarinagi_refresh_token", ""),
            expires_at=float(self.settings.get("hikarinagi_token_expires_at", 0) or 0),
            last_error=self.secrets.get("hikarinagi_last_error", ""),
        )

    def valid_access_token(self) -> str:
        state = self.token_state()
        if state.access_token and (state.expires_at <= 0 or time.time() + 60 < state.expires_at):
            return state.access_token
        if not state.refresh_token:
            if state.last_error:
                raise HikarinagiError(state.last_error)
            return ""
        return self._refresh(state.refresh_token)

    def authorize_interactive(self, timeout: float = 180) -> str:
        client_id = str(self.settings.get("hikarinagi_client_id", "")).strip()
        if not client_id:
            raise HikarinagiError("Set a Hikarinagi OAuth Client ID first.")
        verifier = _random_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state = _random_urlsafe(24)
        nonce = _random_urlsafe(24)
        result: dict[str, str] = {}
        complete = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                result.update({key: values[0] for key, values in query.items() if values})
                body = (
                    "<html><body style='font-family:sans-serif;padding:40px'>"
                    "<h2>Tyranor Next Linux</h2>"
                    "<p>Authorization received. You can close this tab.</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                complete.set()

            def log_message(self, fmt: str, *args: object) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "prompt": "consent",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        webbrowser.open(f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")
        if not complete.wait(timeout):
            server.server_close()
            raise HikarinagiError("Authorization timed out.")
        server.server_close()
        if result.get("error"):
            raise HikarinagiError(result.get("error_description") or result["error"])
        if result.get("state") != state:
            raise HikarinagiError("OAuth state mismatch.")
        code = result.get("code", "")
        if not code:
            raise HikarinagiError("Authorization callback did not contain a code.")
        payload = self._exchange(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }
        )
        token = str(payload.get("access_token") or "")
        refresh = str(payload.get("refresh_token") or "")
        if not token or not refresh:
            raise HikarinagiError("Token response is missing access or refresh token.")
        self._validate_nonce(payload, nonce)
        self._save(token, refresh, int(payload.get("expires_in") or 3600))
        return token

    def clear(self) -> None:
        for key in (
            "hikarinagi_access_token",
            "hikarinagi_refresh_token",
            "hikarinagi_last_error",
        ):
            self.secrets.delete(key)
        self.settings.set("hikarinagi_token_expires_at", 0)

    def _refresh(self, refresh_token: str) -> str:
        client_id = str(self.settings.get("hikarinagi_client_id", "")).strip()
        if not client_id:
            raise HikarinagiError("Hikarinagi Client ID is missing.")
        try:
            payload = self._exchange(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                }
            )
        except HikarinagiError as exc:
            self.secrets.set("hikarinagi_last_error", str(exc))
            raise
        token = str(payload.get("access_token") or "")
        if not token:
            raise HikarinagiError("Refresh response did not contain an access token.")
        next_refresh = str(payload.get("refresh_token") or refresh_token)
        self._save(token, next_refresh, int(payload.get("expires_in") or 3600))
        return token

    def _exchange(self, form: dict[str, str]) -> dict:
        response = requests.post(
            TOKEN_URL,
            data=form,
            timeout=(15, 25),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "TyranorNextLinux/1.0",
            },
        )
        if response.status_code in {400, 401}:
            try:
                error = response.json().get("error_description") or response.json().get("error")
            except ValueError:
                error = None
            raise HikarinagiError(str(error or "Authorization expired; authorize again."))
        if response.status_code != 200:
            raise HikarinagiError(f"Hikarinagi token endpoint returned {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HikarinagiError("Hikarinagi returned invalid token JSON.") from exc
        if not isinstance(payload, dict):
            raise HikarinagiError("Hikarinagi returned an invalid token response.")
        return payload

    def _save(self, access: str, refresh: str, expires_in: int) -> None:
        self.secrets.set("hikarinagi_access_token", access)
        self.secrets.set("hikarinagi_refresh_token", refresh)
        self.secrets.delete("hikarinagi_last_error")
        self.settings.set(
            "hikarinagi_token_expires_at",
            int(time.time() + max(expires_in, 1)),
        )

    @staticmethod
    def _validate_nonce(payload: dict, expected: str) -> None:
        id_token = str(payload.get("id_token") or "")
        if not id_token:
            return
        parts = id_token.split(".")
        if len(parts) != 3:
            raise HikarinagiError("ID token format is invalid.")
        try:
            padding = "=" * (-len(parts[1]) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        except (ValueError, json.JSONDecodeError) as exc:
            raise HikarinagiError("Unable to parse ID token.") from exc
        if decoded.get("nonce") != expected:
            raise HikarinagiError("ID token nonce mismatch.")


def _random_urlsafe(size: int) -> str:
    return secrets.token_urlsafe(size)[:size]
