from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.llm_cost import LLMCost
from src.models.post import Post

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db)):
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok" if db_status == "ok" else "degraded", "database": db_status}


@router.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_db)):
    counts_result = await session.execute(
        select(Post.status, func.count(Post.id).label("count")).group_by(Post.status)
    )
    post_counts = {row.status: row.count for row in counts_result.fetchall()}

    cost_result = await session.execute(select(func.sum(LLMCost.cost_usd)))
    total_cost = float(cost_result.scalar_one_or_none() or 0.0)

    return {"posts": post_counts, "total_llm_cost_usd": round(total_cost, 6)}
