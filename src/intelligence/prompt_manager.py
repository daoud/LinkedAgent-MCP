from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.prompt_template import PromptTemplate


class PromptManagerError(Exception):
    pass


class PromptManager:
    """Load and render prompt templates from the database."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cache: dict[str, PromptTemplate] = {}

    async def get(self, name: str) -> PromptTemplate:
        """Fetch the active template by name (cached per instance)."""
        if name in self._cache:
            return self._cache[name]
        result = await self._session.execute(
            select(PromptTemplate)
            .where(PromptTemplate.name == name, PromptTemplate.is_active.is_(True))
            .order_by(PromptTemplate.version.desc())
            .limit(1)
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise PromptManagerError(f"No active prompt template found: {name!r}")
        self._cache[name] = template
        return template

    async def render(self, name: str, variables: dict[str, str]) -> str:
        """Fetch template and substitute {key} placeholders."""
        template = await self.get(name)
        try:
            return template.template_text.format_map(variables)
        except KeyError as exc:
            raise PromptManagerError(f"Missing template variable: {exc}") from exc
