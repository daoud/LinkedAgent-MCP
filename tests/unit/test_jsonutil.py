"""Unit tests for src/intelligence/jsonutil.parse_json_object."""
from __future__ import annotations

from src.intelligence.jsonutil import parse_json_object


def test_plain_object():
    assert parse_json_object('{"safe": true, "reason": "ok"}') == {"safe": True, "reason": "ok"}


def test_markdown_fenced():
    text = 'Sure, here is the result:\n```json\n{"safe": false, "reason": "bad"}\n```'
    assert parse_json_object(text) == {"safe": False, "reason": "bad"}


def test_fence_without_lang():
    assert parse_json_object("```\n{\"ok\": true}\n```") == {"ok": True}


def test_prose_around_object():
    text = 'I think this is fine. {"ok": true, "issues": []} Hope that helps.'
    assert parse_json_object(text) == {"ok": True, "issues": []}


def test_returns_none_for_garbage():
    assert parse_json_object("this is not json at all") is None
    assert parse_json_object("") is None
    assert parse_json_object("[1, 2, 3]") is None  # not an object


def test_nested_object():
    assert parse_json_object('{"a": {"b": 1}, "c": [1,2]}') == {"a": {"b": 1}, "c": [1, 2]}


def test_prefers_fenced_when_both_present():
    text = 'garbage { not valid ```json\n{"real": 1}\n```'
    assert parse_json_object(text) == {"real": 1}
