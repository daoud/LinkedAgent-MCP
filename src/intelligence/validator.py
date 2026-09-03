from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import yaml

_HASHTAG_RE = re.compile(r"#\w+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

_RULES_PATH = Path(__file__).parent / "validation_rules.yaml"

_TONE_SYSTEM = (
    "You are a LinkedIn content quality reviewer. "
    "Check the post for: spam-like language, misleading claims, "
    "unprofessional tone, or inappropriate content. "
    "Respond ONLY with JSON (no markdown): "
    '{"ok": true|false, "issues": ["<short description>"]}'
)


@dataclass
class ValidationIssue:
    rule: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    char_count: int = 0
    hashtag_count: int = 0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _load_rules(path: Path | None = None) -> dict:
    p = path or _RULES_PATH
    with open(p) as f:
        return yaml.safe_load(f).get("linkedin", {})


class Validator:
    """Post validation engine: structural rules + optional LLM tone check."""

    def __init__(
        self,
        api_key: str | None = None,
        rules_path: Path | None = None,
        _client: Any | None = None,
    ) -> None:
        self._rules = _load_rules(rules_path)
        self._client = _client or anthropic.Anthropic(api_key=api_key)

    def validate(self, post_text: str) -> ValidationResult:
        issues: list[ValidationIssue] = []
        char_count = len(post_text)
        hashtags = _HASHTAG_RE.findall(post_text)
        urls = _URL_RE.findall(post_text)

        max_chars = self._rules.get("max_chars", 3000)
        min_chars = self._rules.get("min_chars", 50)
        max_hashtags = self._rules.get("max_hashtags", 30)
        max_urls = self._rules.get("max_urls", 5)
        forbidden = [w.lower() for w in self._rules.get("forbidden_words", [])]

        if char_count > max_chars:
            issues.append(ValidationIssue(
                "max_chars",
                f"Post is {char_count} chars (limit {max_chars})",
            ))
        if char_count < min_chars:
            issues.append(ValidationIssue(
                "min_chars",
                f"Post is {char_count} chars (minimum {min_chars})",
            ))
        if len(hashtags) > max_hashtags:
            issues.append(ValidationIssue(
                "max_hashtags",
                f"Too many hashtags: {len(hashtags)} (max {max_hashtags})",
            ))
        if len(urls) > max_urls:
            issues.append(ValidationIssue(
                "max_urls",
                f"Too many URLs: {len(urls)} (max {max_urls})",
                severity="warning",
            ))
        post_text_lower = post_text.lower()
        for word in forbidden:
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", post_text_lower):
                issues.append(ValidationIssue(
                    "forbidden_word",
                    f"Forbidden phrase detected: {word!r}",
                ))

        model = ""
        input_tokens = 0
        output_tokens = 0
        if self._rules.get("tone_check", True) and post_text.strip():
            tone_issues, model, input_tokens, output_tokens = self._llm_tone_check(post_text)
            issues.extend(tone_issues)

        passed = all(i.severity != "error" for i in issues)
        return ValidationResult(
            passed=passed,
            issues=issues,
            char_count=char_count,
            hashtag_count=len(hashtags),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _llm_tone_check(self, post_text: str) -> tuple[list[ValidationIssue], str, int, int]:
        model = self._rules.get("tone_model", "claude-sonnet-5")
        response = self._client.messages.create(
            model=model,
            max_tokens=512,
            system=_TONE_SYSTEM,
            messages=[{"role": "user", "content": post_text}],
        )
        used_model = getattr(response, "model", model)
        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens

        text = next((b.text for b in response.content if b.type == "text"), "{}")
        try:
            data: dict = json.loads(text)
        except json.JSONDecodeError:
            return [], used_model, in_tok, out_tok
        if data.get("ok", True):
            return [], used_model, in_tok, out_tok
        issues = [
            ValidationIssue("tone", msg, severity="warning")
            for msg in data.get("issues", [])
        ]
        return issues, used_model, in_tok, out_tok
