from __future__ import annotations

from sqlalchemy import select

from src.config import get_settings
from src.database import AsyncSessionLocal
from src.intelligence.validator import Validator
from src.models.post import Post
from src.pipeline.state import PipelineState


async def validate_node(state: PipelineState) -> dict:
    text = state["transformed_text"]
    post_id = state["post_id"]
    settings = get_settings()

    validator = Validator(api_key=settings.anthropic_api_key)
    result = validator.validate(text)

    issues = [
        {"rule": i.rule, "message": i.message, "severity": i.severity}
        for i in result.issues
    ]

    if not result.passed:
        first_error = issues[0]["message"] if issues else "unknown"
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(Post).where(Post.id == post_id))
            post = r.scalar_one()
            post.status = "failed"
            post.last_error = f"Validation failed: {first_error}"
            post.failed_at_node = "validate"
            await session.commit()

        return {
            "validation_passed": False,
            "validation_issues": issues,
            "error": f"Validation failed: {first_error}",
            "failed_node": "validate",
        }

    return {"validation_passed": True, "validation_issues": issues}
