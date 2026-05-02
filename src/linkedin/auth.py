from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


class LinkedInAuth:
    """Manages LinkedIn OAuth2 tokens with auto-refresh support.

    Token storage strategy:
    - dev:  reads from env vars / .env file
    - prod: swap from_settings() to read from a secret manager

    Scopes required: w_member_social  r_liteprofile
    Token lifetime:  60 days (5,184,000 s) for access tokens
    """

    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    REFRESH_BEFORE_DAYS = 7  # auto-refresh when this close to expiry

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = token_expires_at

    # ---- factory -----------------------------------------------------------

    @classmethod
    def from_env(cls) -> "LinkedInAuth":
        """Build from environment variables (reads .env if present)."""
        expires_at: Optional[datetime] = None
        raw_ts = os.getenv("LINKEDIN_TOKEN_EXPIRES_AT")
        if raw_ts:
            expires_at = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)

        return cls(
            client_id=os.getenv("LINKEDIN_CLIENT_ID", ""),
            client_secret=os.getenv("LINKEDIN_CLIENT_SECRET", ""),
            access_token=os.getenv("LINKEDIN_ACCESS_TOKEN", ""),
            refresh_token=os.getenv("LINKEDIN_REFRESH_TOKEN"),
            token_expires_at=expires_at,
        )

    @classmethod
    def from_settings(cls, settings) -> "LinkedInAuth":
        """Build from a pydantic Settings instance."""
        expires_at: Optional[datetime] = None
        raw_ts = os.getenv("LINKEDIN_TOKEN_EXPIRES_AT")  # not in Settings model
        if raw_ts:
            expires_at = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)

        return cls(
            client_id=settings.linkedin_client_id or "",
            client_secret=settings.linkedin_client_secret or "",
            access_token=settings.linkedin_access_token or "",
            refresh_token=settings.linkedin_refresh_token,
            token_expires_at=expires_at,
        )

    # ---- token management --------------------------------------------------

    def get_access_token(self) -> str:
        """Return a valid access token, auto-refreshing if close to expiry."""
        if self.is_token_expired() and self._refresh_token:
            return self.do_refresh()
        return self._access_token

    def do_refresh(self) -> str:
        """Exchange the refresh token for a new access token."""
        if not self._refresh_token:
            raise ValueError("No refresh token available — re-authorize via linkedin_first_auth.py")

        response = httpx.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
        if "expires_in" in data:
            self._token_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=data["expires_in"]
            )
        return self._access_token

    def is_token_expired(self) -> bool:
        """True when the token has expired or is within REFRESH_BEFORE_DAYS of expiry."""
        if self._token_expires_at is None:
            return False
        threshold = self._token_expires_at - timedelta(days=self.REFRESH_BEFORE_DAYS)
        return datetime.now(timezone.utc) >= threshold

    def days_until_expiry(self) -> Optional[float]:
        """Return days remaining until expiry, or None if expiry is unknown."""
        if self._token_expires_at is None:
            return None
        delta = self._token_expires_at - datetime.now(timezone.utc)
        return delta.total_seconds() / 86_400

    @property
    def access_token(self) -> str:
        return self._access_token
