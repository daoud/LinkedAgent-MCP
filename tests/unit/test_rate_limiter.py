"""Unit tests for src/linkedin/rate_limiter.py."""

import time

import pytest

from src.linkedin.rate_limiter import RateLimiter


def test_initial_remaining_equals_max():
    rl = RateLimiter(max_calls_per_day=50)
    assert rl.remaining == 50


def test_wait_if_needed_decrements_remaining():
    rl = RateLimiter(max_calls_per_day=10)
    rl.wait_if_needed()
    assert rl.remaining == 9


def test_multiple_calls_decrement():
    rl = RateLimiter(max_calls_per_day=10)
    for _ in range(5):
        rl.wait_if_needed()
    assert rl.remaining == 5


def test_update_from_headers_sets_remaining():
    rl = RateLimiter(max_calls_per_day=100)
    rl.update_from_headers({"x-ratelimit-remaining": "42"})
    assert rl.remaining == 42


def test_update_from_headers_sets_limit():
    rl = RateLimiter(max_calls_per_day=100)
    rl.update_from_headers({"x-ratelimit-limit": "200", "x-ratelimit-remaining": "200"})
    assert rl.max_calls == 200


def test_update_from_headers_case_insensitive():
    rl = RateLimiter()
    rl.update_from_headers({"X-RateLimit-Remaining": "77"})
    assert rl.remaining == 77


def test_update_from_headers_empty_dict_noop():
    rl = RateLimiter(max_calls_per_day=100)
    rl.update_from_headers({})
    assert rl.remaining == 100


def test_reset_clears_when_past_reset_time():
    rl = RateLimiter(max_calls_per_day=10)
    # Simulate limit hit + reset time in the past
    rl.update_from_headers(
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(time.time() - 1)}
    )
    # After checking remaining, counter should have reset
    assert rl.remaining == 10


def test_wait_if_needed_resets_after_reset_time():
    rl = RateLimiter(max_calls_per_day=5)
    rl.update_from_headers(
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(time.time() - 1)}
    )
    # Should reset and allow one call
    rl.wait_if_needed()
    assert rl.remaining == 4
