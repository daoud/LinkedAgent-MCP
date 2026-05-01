from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.llm_cost import LLMCost

# USD per 1M tokens (input / output)
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_DEFAULT_PRICING = (5.00, 25.00)


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Return cost in USD for a given model and token counts."""
    in_rate, out_rate = _PRICING.get(model, _DEFAULT_PRICING)
    cost = input_tokens * in_rate / 1_000_000 + output_tokens * out_rate / 1_000_000
    return Decimal(str(round(cost, 6)))


class CostTracker:
    """Record LLM usage costs to the database and enforce monthly budget."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        post_id: uuid.UUID,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> LLMCost:
        cost = calculate_cost(model, input_tokens, output_tokens)
        row = LLMCost(
            post_id=post_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_monthly_total(
        self, year: int | None = None, month: int | None = None
    ) -> Decimal:
        now = datetime.now(timezone.utc)
        year = year or now.year
        month = month or now.month
        result = await self._session.execute(
            select(func.sum(LLMCost.cost_usd)).where(
                func.extract("year", LLMCost.recorded_at) == year,
                func.extract("month", LLMCost.recorded_at) == month,
            )
        )
        total = result.scalar_one_or_none()
        return Decimal(str(total or 0))

    async def is_over_budget(self, monthly_budget: float) -> bool:
        total = await self.get_monthly_total()
        return float(total) >= monthly_budget
