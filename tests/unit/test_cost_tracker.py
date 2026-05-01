"""Unit tests for src/intelligence/cost_tracker.py — no DB required."""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.intelligence.cost_tracker import CostTracker, calculate_cost


# ---------------------------------------------------------------------------
# calculate_cost (pure math — no DB)
# ---------------------------------------------------------------------------

def test_calculate_cost_opus_4_7():
    cost = calculate_cost("claude-opus-4-7", input_tokens=1_000_000, output_tokens=0)
    assert cost == Decimal("5.000000")


def test_calculate_cost_opus_output():
    cost = calculate_cost("claude-opus-4-7", input_tokens=0, output_tokens=1_000_000)
    assert cost == Decimal("25.000000")


def test_calculate_cost_sonnet():
    cost = calculate_cost("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == Decimal("18.000000")


def test_calculate_cost_haiku():
    cost = calculate_cost("claude-haiku-4-5", input_tokens=100_000, output_tokens=100_000)
    expected = Decimal("0.6") / Decimal("1")  # (0.1 + 0.5)
    assert cost == Decimal("0.000600") * Decimal("1000")


def test_calculate_cost_haiku_small():
    # 100 input + 200 output @ haiku pricing
    cost = calculate_cost("claude-haiku-4-5", input_tokens=100, output_tokens=200)
    # 100*1/1e6 + 200*5/1e6 = 0.0001 + 0.001 = 0.0011
    assert cost == Decimal("0.001100")


def test_calculate_cost_unknown_model_uses_default():
    # Unknown model falls back to Opus pricing
    cost = calculate_cost("some-future-model", input_tokens=1_000_000, output_tokens=0)
    assert cost == Decimal("5.000000")


def test_calculate_cost_returns_decimal():
    cost = calculate_cost("claude-sonnet-4-6", input_tokens=500, output_tokens=300)
    assert isinstance(cost, Decimal)


def test_calculate_cost_zero_tokens():
    cost = calculate_cost("claude-opus-4-7", input_tokens=0, output_tokens=0)
    assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# CostTracker.record (mocked async session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_adds_row_to_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    tracker = CostTracker(session)
    post_id = uuid.uuid4()
    row = await tracker.record(
        post_id=post_id,
        model="claude-opus-4-7",
        input_tokens=1000,
        output_tokens=500,
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert row.post_id == post_id
    assert row.model == "claude-opus-4-7"
    assert row.input_tokens == 1000
    assert row.output_tokens == 500
    assert row.cost_usd == calculate_cost("claude-opus-4-7", 1000, 500)


@pytest.mark.asyncio
async def test_record_calculates_correct_cost():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    tracker = CostTracker(session)
    row = await tracker.record(
        post_id=uuid.uuid4(),
        model="claude-sonnet-4-6",
        input_tokens=2000,
        output_tokens=1000,
    )
    expected = calculate_cost("claude-sonnet-4-6", 2000, 1000)
    assert row.cost_usd == expected


# ---------------------------------------------------------------------------
# CostTracker.get_monthly_total + is_over_budget (mocked DB queries)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_monthly_total_returns_sum():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = Decimal("12.345678")
    session.execute = AsyncMock(return_value=mock_result)

    tracker = CostTracker(session)
    total = await tracker.get_monthly_total(2026, 5)
    assert total == Decimal("12.345678")


@pytest.mark.asyncio
async def test_get_monthly_total_none_returns_zero():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    tracker = CostTracker(session)
    total = await tracker.get_monthly_total(2026, 5)
    assert total == Decimal("0")


@pytest.mark.asyncio
async def test_is_over_budget_true():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = Decimal("25.00")
    session.execute = AsyncMock(return_value=mock_result)

    tracker = CostTracker(session)
    assert await tracker.is_over_budget(monthly_budget=20.0) is True


@pytest.mark.asyncio
async def test_is_over_budget_false():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = Decimal("5.00")
    session.execute = AsyncMock(return_value=mock_result)

    tracker = CostTracker(session)
    assert await tracker.is_over_budget(monthly_budget=20.0) is False
