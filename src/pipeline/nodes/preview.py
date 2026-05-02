from __future__ import annotations

from src.config import get_settings
from src.linkedin.auth import LinkedInAuth
from src.linkedin.client import LinkedInClient
from src.pipeline.state import PipelineState


async def preview_node(state: PipelineState) -> dict:
    text = state["transformed_text"]
    settings = get_settings()

    if not settings.linkedin_profile_urn:
        preview = {"dry_run": True, "preview": text[:150], "char_count": len(text)}
        return {"preview_result": preview}

    auth = LinkedInAuth.from_settings(settings)
    client = LinkedInClient(auth=auth, profile_urn=settings.linkedin_profile_urn)
    preview = client.publish(text, dry_run=True)

    return {"preview_result": preview}
