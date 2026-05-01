"""Unit tests for src/intelligence/validator.py — no real API calls."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.intelligence.validator import ValidationIssue, ValidationResult, Validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(ok: bool = True, issues: list[str] | None = None):
    payload = json.dumps({"ok": ok, "issues": issues or []})
    block = MagicMock()
    block.type = "text"
    block.text = payload
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def _validator(ok: bool = True, issues: list[str] | None = None) -> Validator:
    return Validator(_client=_make_mock_client(ok, issues))


# ---------------------------------------------------------------------------
# Structural rules (no LLM needed — tone_check bypassed by mock)
# ---------------------------------------------------------------------------

def test_valid_post_passes():
    v = _validator(ok=True)
    result = v.validate("This is a solid LinkedIn post about leadership and innovation.")
    assert result.passed is True
    assert result.char_count > 0


def test_too_long_fails():
    v = _validator(ok=True)
    long_post = "A" * 3001
    result = v.validate(long_post)
    assert result.passed is False
    rules = [i.rule for i in result.issues]
    assert "max_chars" in rules


def test_too_short_fails():
    v = _validator(ok=True)
    result = v.validate("Hi!")
    assert result.passed is False
    rules = [i.rule for i in result.issues]
    assert "min_chars" in rules


def test_too_many_hashtags_fails():
    v = _validator(ok=True)
    hashtags = " ".join(f"#tag{i}" for i in range(31))
    post = f"Great post about innovation. {hashtags}"
    result = v.validate(post)
    assert result.passed is False
    assert any(i.rule == "max_hashtags" for i in result.issues)


def test_forbidden_word_detected():
    v = _validator(ok=True)
    result = v.validate("This is a guaranteed way to earn free money click here!")
    error_rules = [i.rule for i in result.issues if i.severity == "error"]
    assert "forbidden_word" in error_rules


def test_url_count_warning_not_error():
    v = _validator(ok=True)
    urls = " ".join(f"https://example{i}.com" for i in range(6))
    post = f"Check these links out: {urls}. Great content about technology and career growth!"
    result = v.validate(post)
    url_issues = [i for i in result.issues if i.rule == "max_urls"]
    assert url_issues
    assert all(i.severity == "warning" for i in url_issues)
    # Warnings alone don't fail validation
    non_url_errors = [i for i in result.issues if i.rule != "max_urls" and i.severity == "error"]
    if not non_url_errors:
        assert result.passed is True


def test_char_count_and_hashtag_count_returned():
    v = _validator(ok=True)
    result = v.validate("Hello #LinkedIn world! #AI is #great.")
    assert result.char_count == len("Hello #LinkedIn world! #AI is #great.")
    assert result.hashtag_count == 3


# ---------------------------------------------------------------------------
# LLM tone check
# ---------------------------------------------------------------------------

def test_llm_tone_ok_no_extra_issues():
    v = _validator(ok=True)
    result = v.validate("Sharing insights from my latest project. Proud of the team's work.")
    tone_issues = [i for i in result.issues if i.rule == "tone"]
    assert len(tone_issues) == 0


def test_llm_tone_warns_on_issues():
    v = _validator(ok=False, issues=["Overly promotional language"])
    result = v.validate("Buy our product it is amazing must have now!")
    tone_issues = [i for i in result.issues if i.rule == "tone"]
    assert len(tone_issues) > 0
    # Tone issues are warnings, not errors — post may still pass structurally
    assert all(i.severity == "warning" for i in tone_issues)


def test_llm_json_parse_error_returns_no_tone_issues():
    """Malformed LLM response during tone check → no tone issues added."""
    block = MagicMock()
    block.type = "text"
    block.text = "INVALID JSON"
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response

    v = Validator(_client=client)
    result = v.validate("A decent LinkedIn post about technology trends.")
    tone_issues = [i for i in result.issues if i.rule == "tone"]
    assert len(tone_issues) == 0


def test_custom_rules_path(tmp_path):
    """Validator loads rules from a custom YAML file."""
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        "linkedin:\n  max_chars: 100\n  min_chars: 10\n  max_hashtags: 5\n"
        "  max_urls: 2\n  forbidden_words: []\n  tone_check: false\n"
    )
    v = Validator(rules_path=rules_file, _client=_make_mock_client())
    result = v.validate("A" * 101)
    assert result.passed is False
    assert any(i.rule == "max_chars" for i in result.issues)
