"""Lenient JSON extraction for LLM responses.

Models sometimes wrap JSON in ```json fences or add a sentence before/after
it even when told not to. This pulls the first well-formed object out.
"""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: str) -> dict | None:
    """Return the first JSON object found in *text*, or None if there is none."""
    if not text:
        return None
    candidates = [text.strip()]
    m = _FENCE_RE.search(text)
    if m:
        candidates.insert(0, m.group(1).strip())
    # a bare {...} span anywhere in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for c in candidates:
        try:
            obj = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None
