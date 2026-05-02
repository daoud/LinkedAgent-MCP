"""Unit tests for Phase 9 — Observability + Security."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import health
from src.database import get_db


# ---------------------------------------------------------------------------
# T-9.1: Structured logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_sets_log_level_from_settings(self):
        from src.observability.logging import configure_logging

        settings = MagicMock()
        settings.log_level = "DEBUG"
        settings.environment = "production"

        configure_logging(settings)

        assert logging.getLogger().level == logging.DEBUG

    def test_uses_console_renderer_in_development(self):
        from src.observability.logging import configure_logging

        settings = MagicMock()
        settings.log_level = "INFO"
        settings.environment = "development"

        configure_logging(settings)  # should not raise

    def test_uses_json_renderer_in_production(self):
        from src.observability.logging import configure_logging

        settings = MagicMock()
        settings.log_level = "WARNING"
        settings.environment = "production"

        configure_logging(settings)  # should not raise

    def test_get_logger_returns_bound_logger(self):
        from src.observability.logging import get_logger

        logger = get_logger("test")
        assert logger is not None


# ---------------------------------------------------------------------------
# T-9.2: Prometheus metrics
# ---------------------------------------------------------------------------


class TestPrometheusMetrics:
    def test_counters_increment(self):
        from src.observability.metrics import pipeline_runs_total

        before = pipeline_runs_total.labels(status="success")._value.get()
        pipeline_runs_total.labels(status="success").inc()
        after = pipeline_runs_total.labels(status="success")._value.get()
        assert after == before + 1

    def test_get_metrics_output_returns_bytes(self):
        from src.observability.metrics import get_metrics_output

        output = get_metrics_output()
        assert isinstance(output, bytes)
        assert len(output) > 0

    def test_metrics_output_contains_pipeline_runs(self):
        from src.observability.metrics import get_metrics_output, pipeline_runs_total

        pipeline_runs_total.labels(status="error").inc()
        output = get_metrics_output().decode()
        assert "pipeline_runs_total" in output

    def test_prometheus_endpoint_returns_200(self):
        @asynccontextmanager
        async def _lifespan(app: FastAPI):
            yield

        app = FastAPI(lifespan=_lifespan)
        app.include_router(health.router)

        with TestClient(app) as client:
            r = client.get("/prometheus")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]

    def test_prometheus_endpoint_body_is_valid_exposition(self):
        @asynccontextmanager
        async def _lifespan(app: FastAPI):
            yield

        app = FastAPI(lifespan=_lifespan)
        app.include_router(health.router)

        with TestClient(app) as client:
            r = client.get("/prometheus")
        assert "pipeline_runs_total" in r.text


# ---------------------------------------------------------------------------
# T-9.3: OpenTelemetry tracing
# ---------------------------------------------------------------------------


class TestTracing:
    def test_configure_tracing_does_not_raise(self):
        from src.observability.tracing import configure_tracing

        configure_tracing(service_name="test-service")

    def test_get_tracer_returns_tracer(self):
        from opentelemetry import trace

        from src.observability.tracing import get_tracer

        tracer = get_tracer("test")
        assert tracer is not None

    def test_trace_span_context_manager(self):
        from src.observability.tracing import configure_tracing, trace_span

        configure_tracing(service_name="test-service")

        with trace_span("test-span", attributes={"key": "value"}) as span:
            assert span is not None

    def test_trace_span_without_attributes(self):
        from src.observability.tracing import configure_tracing, trace_span

        configure_tracing(service_name="test-service")

        with trace_span("bare-span") as span:
            assert span is not None


# ---------------------------------------------------------------------------
# T-9.4: Secrets management
# ---------------------------------------------------------------------------


class TestSecretsBackend:
    def test_env_backend_reads_env_var(self, monkeypatch):
        from src.secrets import EnvSecretsBackend

        monkeypatch.setenv("MY_SECRET", "supersecret")
        backend = EnvSecretsBackend()
        assert backend.get("MY_SECRET") == "supersecret"

    def test_env_backend_returns_default_when_missing(self):
        from src.secrets import EnvSecretsBackend

        backend = EnvSecretsBackend()
        assert backend.get("__NONEXISTENT_KEY__", "fallback") == "fallback"

    def test_env_backend_returns_none_when_no_default(self):
        from src.secrets import EnvSecretsBackend

        backend = EnvSecretsBackend()
        assert backend.get("__NONEXISTENT_KEY__") is None

    def test_get_secret_uses_env_by_default(self, monkeypatch):
        from src import secrets as secrets_module

        monkeypatch.setenv("SECRETS_BACKEND", "env")
        monkeypatch.setenv("PIPELINE_TEST_KEY", "hello")
        secrets_module.get_secrets.cache_clear()
        assert secrets_module.get_secret("PIPELINE_TEST_KEY") == "hello"
        secrets_module.get_secrets.cache_clear()

    def test_get_secret_returns_default_when_key_missing(self, monkeypatch):
        from src import secrets as secrets_module

        monkeypatch.setenv("SECRETS_BACKEND", "env")
        secrets_module.get_secrets.cache_clear()
        result = secrets_module.get_secret("__NO_SUCH_KEY__", "default_val")
        assert result == "default_val"
        secrets_module.get_secrets.cache_clear()

    def test_aws_backend_falls_back_on_error(self):
        from src.secrets import AWSSecretsBackend

        backend = AWSSecretsBackend.__new__(AWSSecretsBackend)
        backend._cache = {}
        backend._client = MagicMock()
        backend._client.get_secret_value.side_effect = Exception("no aws")

        result = backend.get("MY_KEY", "fallback")
        assert result == "fallback"

    def test_aws_backend_uses_cache_on_second_call(self):
        from src.secrets import AWSSecretsBackend

        backend = AWSSecretsBackend.__new__(AWSSecretsBackend)
        backend._cache = {"CACHED_KEY": "cached_value"}
        backend._client = MagicMock()

        result = backend.get("CACHED_KEY")
        assert result == "cached_value"
        backend._client.get_secret_value.assert_not_called()

    def test_make_backend_returns_env_by_default(self, monkeypatch):
        from src import secrets as secrets_module

        monkeypatch.delenv("SECRETS_BACKEND", raising=False)
        secrets_module.get_secrets.cache_clear()
        backend = secrets_module._make_backend()
        assert isinstance(backend, secrets_module.EnvSecretsBackend)
        secrets_module.get_secrets.cache_clear()
