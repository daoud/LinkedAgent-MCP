"""Unit tests for src/linkedin/auth.py — no real API calls."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from src.linkedin.auth import LinkedInAuth


def _make_auth(
    *,
    access_token: str = "acc_token",
    refresh_token: str | None = "ref_token",
    expires_at: datetime | None = None,
) -> LinkedInAuth:
    return LinkedInAuth(
        client_id="client_id",
        client_secret="client_secret",
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=expires_at,
    )


# ---- is_token_expired ------------------------------------------------------


def test_no_expiry_is_not_expired():
    auth = _make_auth(expires_at=None)
    assert auth.is_token_expired() is False


def test_far_future_expiry_is_not_expired():
    future = datetime.now(timezone.utc) + timedelta(days=30)
    auth = _make_auth(expires_at=future)
    assert auth.is_token_expired() is False


def test_within_7_days_is_expired():
    soon = datetime.now(timezone.utc) + timedelta(days=5)
    auth = _make_auth(expires_at=soon)
    assert auth.is_token_expired() is True


def test_past_expiry_is_expired():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    auth = _make_auth(expires_at=past)
    assert auth.is_token_expired() is True


# ---- days_until_expiry -----------------------------------------------------


def test_days_until_expiry_none_when_unknown():
    auth = _make_auth(expires_at=None)
    assert auth.days_until_expiry() is None


def test_days_until_expiry_positive():
    future = datetime.now(timezone.utc) + timedelta(days=20)
    auth = _make_auth(expires_at=future)
    days = auth.days_until_expiry()
    assert days is not None
    assert 19 < days < 21


# ---- get_access_token (no refresh needed) ----------------------------------


def test_get_access_token_returns_current_when_valid():
    auth = _make_auth(access_token="valid_token", expires_at=None)
    assert auth.get_access_token() == "valid_token"


# ---- do_refresh ------------------------------------------------------------


@respx.mock
def test_do_refresh_updates_token():
    respx.post("https://www.linkedin.com/oauth/v2/accessToken").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "expires_in": 5_184_000,
            },
        )
    )
    auth = _make_auth(access_token="old_token", refresh_token="old_refresh")
    new_token = auth.do_refresh()
    assert new_token == "new_access"
    assert auth.access_token == "new_access"
    assert auth.days_until_expiry() is not None


@respx.mock
def test_do_refresh_raises_on_api_error():
    respx.post("https://www.linkedin.com/oauth/v2/accessToken").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    auth = _make_auth()
    with pytest.raises(httpx.HTTPStatusError):
        auth.do_refresh()


def test_do_refresh_raises_without_refresh_token():
    auth = _make_auth(refresh_token=None)
    with pytest.raises(ValueError, match="No refresh token"):
        auth.do_refresh()


# ---- auto-refresh via get_access_token -------------------------------------


@respx.mock
def test_get_access_token_auto_refreshes_near_expiry():
    respx.post("https://www.linkedin.com/oauth/v2/accessToken").mock(
        return_value=httpx.Response(200, json={"access_token": "refreshed_token"})
    )
    soon = datetime.now(timezone.utc) + timedelta(days=3)
    auth = _make_auth(access_token="old_token", expires_at=soon)
    token = auth.get_access_token()
    assert token == "refreshed_token"


# ---- from_env --------------------------------------------------------------


def test_from_env(monkeypatch):
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "cid")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "csec")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("LINKEDIN_REFRESH_TOKEN", "ref")
    monkeypatch.delenv("LINKEDIN_TOKEN_EXPIRES_AT", raising=False)

    auth = LinkedInAuth.from_env()
    assert auth.client_id == "cid"
    assert auth.access_token == "tok"
    assert auth.days_until_expiry() is None
