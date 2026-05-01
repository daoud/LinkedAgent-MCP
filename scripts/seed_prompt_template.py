#!/usr/bin/env python
"""Seed the database with the default LinkedIn post prompt template."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

DEFAULT_TEMPLATE = """\
You are a professional LinkedIn content writer. Transform the following source \
content into an engaging LinkedIn post.

Source Content:
{content}

Instructions:
- Tone: {tone} (default: professional and insightful)
- Length: 1,200–1,500 characters (LinkedIn's engagement sweet spot)
- Structure: Hook → Core Value → Key Insight → Call-to-Action
- Hashtags: 3–5 relevant hashtags at the end (e.g., #Leadership #Innovation #AI)
- CTA: End with an open question to drive comments
- Format: Plain text with line breaks — no markdown, no bullet symbols
- Hook: Start with a compelling first sentence that makes readers click "see more"
- Emojis: 2–3 max, placed strategically

Output only the LinkedIn post text — nothing else.\
"""

DEFAULT_VARIABLES = {
    "content": "The source material to transform into a LinkedIn post",
    "tone": "professional | conversational | thought-leadership | storytelling",
}


async def seed() -> None:
    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.prompt_template import PromptTemplate

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PromptTemplate).where(PromptTemplate.name == "linkedin_post_default")
        )
        if result.scalar_one_or_none() is not None:
            print("Default prompt template already exists — skipping.")
            return

        template = PromptTemplate(
            name="linkedin_post_default",
            version=1,
            template_text=DEFAULT_TEMPLATE,
            variables=DEFAULT_VARIABLES,
            is_active=True,
        )
        session.add(template)
        await session.commit()
        print("Default prompt template inserted.")


if __name__ == "__main__":
    asyncio.run(seed())
