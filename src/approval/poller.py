from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.approval.queue import ApprovalQueue
from src.approval.sheets_client import SheetsClient
from src.approval.slack_notifier import SlackNotifier
from src.config import Settings, get_settings
from src.models.approval import Approval


class ApprovalPoller:
    """Polls Google Sheets for human decisions and syncs them to the database."""

    def __init__(
        self,
        session: AsyncSession,
        sheets: SheetsClient,
        notifier: SlackNotifier,
        settings: Optional[Settings] = None,
    ) -> None:
        self._session = session
        self._sheets = sheets
        self._notifier = notifier
        self._queue = ApprovalQueue(session, settings)
        self._settings = settings or get_settings()

    async def poll_once(self) -> list[Approval]:
        """
        One poll cycle:
          1. Expire timed-out approvals.
          2. Read decisions from the sheet.
          3. Record each decision in the DB and notify Slack.
        Returns approvals that were actioned this cycle.
        """
        actioned: list[Approval] = []

        expired = await self._queue.expire_timed_out()
        for approval in expired:
            await self._notifier.notify_decision(approval)
        actioned.extend(expired)

        decisions = self._sheets.read_decisions()
        for entry in decisions:
            try:
                approval = await self._queue.record_decision(
                    approval_id=entry["approval_id"],
                    decision=entry["decision"],
                    decided_by=entry.get("decided_by", "sheet"),
                )
                await self._notifier.notify_decision(approval)
                actioned.append(approval)
            except Exception:
                pass

        return actioned
