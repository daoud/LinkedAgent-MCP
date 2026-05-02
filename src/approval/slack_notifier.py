from __future__ import annotations

from typing import Optional

import httpx

from src.config import Settings, get_settings
from src.models.approval import Approval


class SlackNotifier:
    """Sends approval notifications to a Slack webhook."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    async def notify_pending(self, approval: Approval) -> None:
        """Post a message when a new post enters the approval queue."""
        if not self._settings.slack_webhook_url:
            return
        text = (
            f":pencil: *New post awaiting approval*\n"
            f"ID: `{approval.id}`\n"
            f"Preview:\n```{approval.preview_text[:300]}```"
        )
        await self._post({"text": text})

    async def notify_decision(self, approval: Approval) -> None:
        """Post a message when an approval decision is recorded."""
        if not self._settings.slack_webhook_url:
            return
        icon = ":white_check_mark:" if approval.decision == "approved" else ":x:"
        text = (
            f"{icon} *Approval {approval.decision}*\n"
            f"ID: `{approval.id}`  by `{approval.decided_by or 'unknown'}`"
        )
        await self._post({"text": text})

    async def _post(self, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self._settings.slack_webhook_url, json=payload)
            response.raise_for_status()
