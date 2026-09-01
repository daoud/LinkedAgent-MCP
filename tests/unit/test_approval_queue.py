"""Unit tests for src/approval/queue.py, sheets_client.py, slack_notifier.py, poller.py."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from src.approval.queue import ApprovalQueue
from src.approval.slack_notifier import SlackNotifier
from src.approval.poller import ApprovalPoller
from src.config import Settings
from src.models.approval import Approval
from src.models.post import Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**kwargs) -> Settings:
    base = dict(
        timezone="UTC",
        post_slots="09:00",
        daily_post_limit=1,
        database_url="postgresql://pipeline:pipeline@localhost:5433/pipeline",
        anthropic_api_key="test-key",
        approval_timeout_h=24,
        slack_webhook_url="https://hooks.slack.com/test",
    )
    base.update(kwargs)
    return Settings(**base)


def _post(status: str = "processing") -> Post:
    p = Post()
    p.id = uuid.uuid4()
    p.transformed_text = "Hello LinkedIn!"
    p.status = status
    return p


def _approval(
    decision: str = "pending",
    expires_at: datetime | None = None,
    post_id: uuid.UUID | None = None,
) -> Approval:
    a = Approval()
    a.id = uuid.uuid4()
    a.post_id = post_id or uuid.uuid4()
    a.preview_text = "Hello LinkedIn!"
    a.decision = decision
    a.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(hours=24))
    return a


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one.return_value = None
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# ApprovalQueue.enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_creates_approval_and_sets_status():
    session = _mock_session()
    post = _post()
    q = ApprovalQueue(session, _settings())
    approval = await q.enqueue(post)

    assert isinstance(approval, Approval)
    assert approval.post_id == post.id
    assert approval.decision == "pending"
    assert post.status == "awaiting_approval"
    session.add.assert_called_once_with(approval)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_sets_expires_at_in_future():
    session = _mock_session()
    post = _post()
    before = datetime.now(timezone.utc)
    q = ApprovalQueue(session, _settings(approval_timeout_h=2))
    approval = await q.enqueue(post)
    after = datetime.now(timezone.utc)

    assert approval.expires_at > before
    assert approval.expires_at < after + timedelta(hours=3)


@pytest.mark.asyncio
async def test_enqueue_preview_truncated_to_content():
    session = _mock_session()
    post = _post()
    post.transformed_text = "My post content"
    q = ApprovalQueue(session, _settings())
    approval = await q.enqueue(post)
    assert approval.preview_text == "My post content"


# ---------------------------------------------------------------------------
# ApprovalQueue.get_pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_returns_list_from_db():
    session = _mock_session()
    approvals = [_approval(), _approval()]
    result = MagicMock()
    result.scalars.return_value.all.return_value = approvals
    session.execute.return_value = result

    q = ApprovalQueue(session, _settings())
    found = await q.get_pending()
    assert found == approvals
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_pending_returns_empty_when_none():
    session = _mock_session()
    q = ApprovalQueue(session, _settings())
    found = await q.get_pending()
    assert found == []


# ---------------------------------------------------------------------------
# ApprovalQueue.expire_timed_out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expire_timed_out_marks_decision_timeout():
    session = _mock_session()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    a = _approval(decision="pending", expires_at=past)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [a]
    session.execute.return_value = result

    q = ApprovalQueue(session, _settings())
    expired = await q.expire_timed_out()

    assert len(expired) == 1
    assert expired[0].decision == "timeout"
    assert expired[0].decided_at is not None


@pytest.mark.asyncio
async def test_expire_timed_out_returns_empty_when_none():
    session = _mock_session()
    q = ApprovalQueue(session, _settings())
    expired = await q.expire_timed_out()
    assert expired == []


@pytest.mark.asyncio
async def test_expire_timed_out_flushes_only_when_items_found():
    session = _mock_session()
    q = ApprovalQueue(session, _settings())
    await q.expire_timed_out()
    session.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# ApprovalQueue.record_decision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_decision_approved():
    session = _mock_session()
    a = _approval(decision="pending")
    result = MagicMock()
    result.scalar_one.return_value = a
    session.execute.return_value = result

    q = ApprovalQueue(session, _settings())
    updated = await q.record_decision(a.id, "approved", "alice")

    assert updated.decision == "approved"
    assert updated.decided_by == "alice"
    assert updated.decided_at is not None


@pytest.mark.asyncio
async def test_record_decision_rejected():
    session = _mock_session()
    a = _approval(decision="pending")
    result = MagicMock()
    result.scalar_one.return_value = a
    session.execute.return_value = result

    q = ApprovalQueue(session, _settings())
    updated = await q.record_decision(a.id, "rejected", "bob")

    assert updated.decision == "rejected"
    assert updated.decided_by == "bob"


# ---------------------------------------------------------------------------
# SlackNotifier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_pending_posts_to_webhook():
    s = _settings(slack_webhook_url="https://hooks.slack.com/test")
    notifier = SlackNotifier(s)
    a = _approval()

    with respx.mock:
        route = respx.post("https://hooks.slack.com/test").mock(
            return_value=httpx.Response(200)
        )
        await notifier.notify_pending(a)
    assert route.called


@pytest.mark.asyncio
async def test_notify_pending_skips_when_no_webhook():
    s = _settings(slack_webhook_url=None)
    notifier = SlackNotifier(s)
    a = _approval()
    # Should not raise even though no URL is configured
    await notifier.notify_pending(a)


@pytest.mark.asyncio
async def test_notify_decision_approved_posts_to_webhook():
    s = _settings(slack_webhook_url="https://hooks.slack.com/test")
    notifier = SlackNotifier(s)
    a = _approval(decision="approved")
    a.decided_by = "alice"

    with respx.mock:
        route = respx.post("https://hooks.slack.com/test").mock(
            return_value=httpx.Response(200)
        )
        await notifier.notify_decision(a)
    assert route.called


@pytest.mark.asyncio
async def test_notify_decision_skips_when_no_webhook():
    s = _settings(slack_webhook_url=None)
    notifier = SlackNotifier(s)
    a = _approval(decision="rejected")
    await notifier.notify_decision(a)


# ---------------------------------------------------------------------------
# ApprovalPoller
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_once_processes_sheet_decisions():
    session = _mock_session()
    sheets = MagicMock()
    notifier = AsyncMock()

    approval_id = uuid.uuid4()
    sheets.read_decisions.return_value = [
        {"approval_id": approval_id, "decision": "approved", "decided_by": "alice"}
    ]

    a = _approval(decision="approved")
    a.decided_by = "alice"

    # expire_timed_out: no expired items
    expired_result = MagicMock()
    expired_result.scalars.return_value.all.return_value = []

    # record_decision: return the approval
    decision_result = MagicMock()
    decision_result.scalar_one.return_value = a

    call_count = 0

    async def mock_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return expired_result
        return decision_result

    session.execute = mock_execute

    poller = ApprovalPoller(session, sheets, notifier, _settings())
    actioned = await poller.poll_once()

    assert len(actioned) >= 1
    notifier.notify_decision.assert_awaited()


@pytest.mark.asyncio
async def test_poll_once_returns_empty_when_no_decisions():
    session = _mock_session()
    sheets = MagicMock()
    notifier = AsyncMock()
    sheets.read_decisions.return_value = []

    poller = ApprovalPoller(session, sheets, notifier, _settings())
    actioned = await poller.poll_once()
    assert actioned == []


@pytest.mark.asyncio
async def test_poll_once_handles_record_decision_error_gracefully():
    """record_decision raising an exception should not crash poll_once."""
    session = _mock_session()
    sheets = MagicMock()
    notifier = AsyncMock()
    approval_id = uuid.uuid4()
    sheets.read_decisions.return_value = [
        {"approval_id": approval_id, "decision": "approved", "decided_by": "alice"}
    ]

    # expire_timed_out returns empty
    expired_result = MagicMock()
    expired_result.scalars.return_value.all.return_value = []

    # record_decision raises
    error_result = MagicMock()
    error_result.scalar_one.side_effect = Exception("DB error")

    call_count = 0

    async def mock_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return expired_result
        return error_result

    session.execute = mock_execute

    poller = ApprovalPoller(session, sheets, notifier, _settings())
    actioned = await poller.poll_once()
    assert actioned == []
