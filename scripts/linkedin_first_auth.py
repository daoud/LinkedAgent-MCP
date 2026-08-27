#!/usr/bin/env python
"""One-time LinkedIn OAuth2 authorization flow.

Run once to obtain LINKEDIN_ACCESS_TOKEN, LINKEDIN_REFRESH_TOKEN, and
LINKEDIN_TOKEN_EXPIRES_AT, then add them to your .env file.

Usage:
    python scripts/linkedin_first_auth.py
"""

from __future__ import annotations

import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import httpx

CALLBACK_PORT = 8080
CALLBACK_URL = f"http://localhost:{CALLBACK_PORT}/auth/callback"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPES = "w_member_social openid profile"

_auth_code: str | None = None
_expected_state: str = ""


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _auth_code = params["code"][0]
            self._respond(
                200,
                b"<h1>Authorization successful!</h1><p>You can close this window.</p>",
            )
        else:
            error = params.get("error_description", params.get("error", ["unknown"]))[0]
            self._respond(400, f"<h1>Authorization failed: {error}</h1>".encode())

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass  # silence request logs


def run() -> None:
    global _expected_state

    client_id = os.getenv("LINKEDIN_CLIENT_ID", "")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print(
            "ERROR: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env\n"
            "       Get them from https://www.linkedin.com/developers/apps"
        )
        sys.exit(1)

    _expected_state = secrets.token_urlsafe(16)

    auth_params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CALLBACK_URL,
            "scope": SCOPES,
            "state": _expected_state,
        }
    )
    auth_url = f"{AUTH_URL}?{auth_params}"

    print(f"\nOpening browser for LinkedIn authorization…")
    print(f"If the browser does not open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print(f"Waiting for callback on http://localhost:{CALLBACK_PORT}/callback …")
    server = HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    server.handle_request()  # blocks until one request is received

    if not _auth_code:
        print("No authorization code received. Exiting.")
        sys.exit(1)

    # Exchange authorization code for tokens
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _auth_code,
            "redirect_uri": CALLBACK_URL,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )

    if response.status_code != 200:
        print(f"Token exchange failed ({response.status_code}): {response.text}")
        sys.exit(1)

    data = response.json()
    access_token: str = data["access_token"]
    refresh_token: str = data.get("refresh_token", "")
    expires_in: int = data.get("expires_in", 5_184_000)  # 60 days default
    expires_at: int = int(time.time()) + expires_in

    print("\n" + "=" * 62)
    print("SUCCESS — add these lines to your .env file:")
    print("=" * 62)
    print(f"LINKEDIN_ACCESS_TOKEN={access_token}")
    if refresh_token:
        print(f"LINKEDIN_REFRESH_TOKEN={refresh_token}")
    print(f"LINKEDIN_TOKEN_EXPIRES_AT={expires_at}")

    # Fetch profile URN
    profile_resp = httpx.get(
        "https://api.linkedin.com/v2/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if profile_resp.status_code == 200:
        person_id = profile_resp.json().get("id", "")
        print(f"LINKEDIN_PROFILE_URN=urn:li:person:{person_id}")

    print("=" * 62 + "\n")


if __name__ == "__main__":
    run()
