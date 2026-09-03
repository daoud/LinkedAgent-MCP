from __future__ import annotations

import urllib.parse
from typing import Optional

import httpx

from src.linkedin.auth import LinkedInAuth
from src.linkedin.rate_limiter import RateLimiter

_BASE_URL = "https://api.linkedin.com/v2"
MAX_POST_LENGTH = 3000


class LinkedInClient:
    """LinkedIn UGC API client.

    All mutating methods support dry_run=True (default) which validates
    the payload and returns a preview dict without touching the API.
    """

    def __init__(
        self,
        auth: LinkedInAuth,
        profile_urn: str,
        rate_limiter: Optional[RateLimiter] = None,
        timeout: float = 30.0,
    ) -> None:
        self.auth = auth
        self.profile_urn = profile_urn
        self._limiter = rate_limiter or RateLimiter()
        self._timeout = timeout

    # ---- publish -----------------------------------------------------------

    def publish(
        self,
        text: str,
        media_urns: Optional[list[str]] = None,
        dry_run: bool = True,
    ) -> dict:
        """Publish a text post to LinkedIn.

        dry_run=True  → validate + return preview dict, no API call
        dry_run=False → POST to UGC API, return {'linkedin_post_id': ...}
        """
        if len(text) > MAX_POST_LENGTH:
            raise ValueError(
                f"Post text is {len(text)} chars — LinkedIn limit is {MAX_POST_LENGTH}"
            )
        if not text.strip():
            raise ValueError("Post text must not be empty")

        payload = self._build_ugc_payload(text, media_urns)

        if dry_run:
            preview = text[:150] + ("…" if len(text) > 150 else "")
            return {
                "dry_run": True,
                "preview": preview,
                "char_count": len(text),
                "author": self.profile_urn,
                "payload": payload,
            }

        self._limiter.wait_if_needed()
        response = httpx.post(
            f"{_BASE_URL}/ugcPosts",
            json=payload,
            headers=self._headers(),
            timeout=self._timeout,
        )
        self._limiter.update_from_headers(response.headers)
        response.raise_for_status()

        post_id = response.headers.get("x-restli-id") or response.json().get("id", "")
        return {"dry_run": False, "linkedin_post_id": post_id}

    # ---- profile -----------------------------------------------------------

    def get_profile(self) -> dict:
        """Return the authenticated user's profile URN and display name."""
        response = httpx.get(
            f"{_BASE_URL}/me",
            headers=self._headers(),
            params={"projection": "(id,firstName,lastName)"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()

        first = _localized(data.get("firstName", {}))
        last = _localized(data.get("lastName", {}))
        return {
            "id": data.get("id", ""),
            "urn": f"urn:li:person:{data.get('id', '')}",
            "name": f"{first} {last}".strip(),
        }

    # ---- media -------------------------------------------------------------

    def upload_image(self, image_bytes: bytes, filename: str = "image.jpg") -> str:
        """Upload an image and return its LinkedIn asset URN."""
        # Step 1 — register upload
        register_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": self.profile_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        reg = httpx.post(
            f"{_BASE_URL}/assets?action=registerUpload",
            json=register_payload,
            headers=self._headers(),
            timeout=self._timeout,
        )
        reg.raise_for_status()
        reg_data = reg.json()

        upload_mechanism = reg_data["value"]["uploadMechanism"]
        upload_url = upload_mechanism[
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn: str = reg_data["value"]["asset"]

        # Step 2 — upload binary
        put = httpx.put(
            upload_url,
            content=image_bytes,
            headers={
                "Authorization": f"Bearer {self.auth.get_access_token()}",
                "Content-Type": "image/jpeg",
            },
            timeout=self._timeout,
        )
        put.raise_for_status()
        return asset_urn

    # ---- delete ------------------------------------------------------------

    def delete_post(self, post_id: str) -> bool:
        """Delete a post by its LinkedIn URN (e.g. urn:li:share:123). True on success.

        The URN goes in the path, so its colons must be percent-encoded; LinkedIn
        replies 204 No Content on success and 404 if it is already gone.
        """
        encoded = urllib.parse.quote(post_id, safe="")
        response = httpx.delete(
            f"{_BASE_URL}/ugcPosts/{encoded}",
            headers=self._headers(),
            timeout=self._timeout,
        )
        return response.status_code in (200, 204, 404)

    # ---- private -----------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _build_ugc_payload(
        self, text: str, media_urns: Optional[list[str]]
    ) -> dict:
        share_content: dict = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "NONE",
        }
        if media_urns:
            share_content["shareMediaCategory"] = "IMAGE"
            share_content["media"] = [
                {"status": "READY", "media": urn} for urn in media_urns
            ]
        return {
            "author": self.profile_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": share_content
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }


def _localized(field: dict) -> str:
    localized = field.get("localized", {})
    return next(iter(localized.values()), "") if localized else ""
