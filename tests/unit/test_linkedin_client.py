"""Unit tests for src/linkedin/client.py — all API calls are mocked."""

import httpx
import pytest
import respx

from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import MAX_POST_LENGTH, LinkedInClient


def _make_client(access_token: str = "test_token") -> LinkedInClient:
    auth = LinkedInAuth(
        client_id="c",
        client_secret="s",
        access_token=access_token,
    )
    return LinkedInClient(auth, profile_urn="urn:li:person:abc123")


# ---- publish dry_run -------------------------------------------------------


def test_publish_dry_run_returns_preview():
    client = _make_client()
    result = client.publish("Hello LinkedIn! #Test", dry_run=True)

    assert result["dry_run"] is True
    assert "Hello LinkedIn!" in result["preview"]
    assert result["char_count"] == len("Hello LinkedIn! #Test")
    assert result["author"] == "urn:li:person:abc123"
    assert "payload" in result


def test_publish_dry_run_truncates_preview_at_150():
    text = "A" * 200
    result = _make_client().publish(text, dry_run=True)
    assert result["char_count"] == 200
    assert len(result["preview"]) <= 151 + 1  # 150 + ellipsis char


def test_publish_dry_run_short_text_no_ellipsis():
    text = "Short post"
    result = _make_client().publish(text, dry_run=True)
    assert result["preview"] == text


def test_publish_raises_on_empty_text():
    with pytest.raises(ValueError, match="empty"):
        _make_client().publish("   ", dry_run=True)


def test_publish_raises_when_too_long():
    text = "x" * (MAX_POST_LENGTH + 1)
    with pytest.raises(ValueError, match=str(MAX_POST_LENGTH)):
        _make_client().publish(text, dry_run=True)


def test_publish_at_exact_limit_passes():
    text = "x" * MAX_POST_LENGTH
    result = _make_client().publish(text, dry_run=True)
    assert result["char_count"] == MAX_POST_LENGTH


# ---- publish live (mocked API) ---------------------------------------------


@respx.mock
def test_publish_live_calls_ugc_api():
    respx.post("https://api.linkedin.com/v2/ugcPosts").mock(
        return_value=httpx.Response(201, headers={"x-restli-id": "urn:li:ugcPost:99"})
    )
    client = _make_client()
    result = client.publish("Real post content", dry_run=False)

    assert result["dry_run"] is False
    assert result["linkedin_post_id"] == "urn:li:ugcPost:99"


@respx.mock
def test_publish_live_raises_on_api_error():
    respx.post("https://api.linkedin.com/v2/ugcPosts").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        _make_client().publish("Post", dry_run=False)


# ---- get_profile -----------------------------------------------------------


@respx.mock
def test_get_profile_returns_urn_and_name():
    respx.get("https://api.linkedin.com/v2/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "abc123",
                "firstName": {"localized": {"en_US": "John"}},
                "lastName": {"localized": {"en_US": "Doe"}},
            },
        )
    )
    profile = _make_client().get_profile()

    assert profile["id"] == "abc123"
    assert profile["urn"] == "urn:li:person:abc123"
    assert profile["name"] == "John Doe"


@respx.mock
def test_get_profile_raises_on_error():
    respx.get("https://api.linkedin.com/v2/me").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        _make_client().get_profile()


# ---- delete_post -----------------------------------------------------------


@respx.mock
def test_delete_post_returns_true_on_204():
    # the URN's colons are percent-encoded into the path
    respx.delete("https://api.linkedin.com/v2/ugcPosts/urn%3Ali%3AugcPost%3A1").mock(
        return_value=httpx.Response(204)
    )
    assert _make_client().delete_post("urn:li:ugcPost:1") is True


@respx.mock
def test_delete_post_treats_404_as_already_gone():
    respx.delete("https://api.linkedin.com/v2/ugcPosts/missing").mock(
        return_value=httpx.Response(404)
    )
    assert _make_client().delete_post("missing") is True


@respx.mock
def test_delete_post_returns_false_on_500():
    respx.delete("https://api.linkedin.com/v2/ugcPosts/x").mock(
        return_value=httpx.Response(500)
    )
    assert _make_client().delete_post("x") is False


# ---- payload structure -----------------------------------------------------


def test_ugc_payload_no_media():
    client = _make_client()
    result = client.publish("Simple text", dry_run=True)
    payload = result["payload"]

    sc = payload["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert sc["shareMediaCategory"] == "NONE"
    assert sc["shareCommentary"]["text"] == "Simple text"
    assert payload["author"] == "urn:li:person:abc123"


def test_ugc_payload_with_media():
    client = _make_client()
    result = client.publish(
        "Post with image", media_urns=["urn:li:digitalmediaAsset:img1"], dry_run=True
    )
    sc = result["payload"]["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert sc["shareMediaCategory"] == "IMAGE"
    assert sc["media"][0]["media"] == "urn:li:digitalmediaAsset:img1"
