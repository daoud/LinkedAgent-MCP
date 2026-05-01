from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import anthropic


@dataclass
class TransformResult:
    post_id: uuid.UUID
    transformed_text: str
    model: str
    input_tokens: int
    output_tokens: int


class Transformer:
    """LLM transform agent — converts raw content into a LinkedIn post.

    Uses Claude Opus 4.7 with adaptive thinking and streaming.
    """

    def __init__(self, api_key: str | None = None, _client: Any | None = None) -> None:
        self._client = _client or anthropic.Anthropic(api_key=api_key)

    def transform(
        self,
        content: str,
        system_prompt: str,
        post_id: uuid.UUID | None = None,
    ) -> TransformResult:
        """Transform raw content into a LinkedIn post via Claude Opus 4.7.

        Streams the response to avoid HTTP timeouts on longer outputs.
        """
        if post_id is None:
            post_id = uuid.uuid4()

        with self._client.messages.stream(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            final = stream.get_final_message()

        text = next((b.text for b in final.content if b.type == "text"), "")

        return TransformResult(
            post_id=post_id,
            transformed_text=text.strip(),
            model=final.model,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )
