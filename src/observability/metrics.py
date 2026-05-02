from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

pipeline_runs_total = Counter(
    "pipeline_runs_total",
    "Total pipeline runs by status",
    ["status"],  # "success" | "error" | "skipped"
    registry=REGISTRY,
)

pipeline_node_duration_seconds = Histogram(
    "pipeline_node_duration_seconds",
    "Pipeline node execution duration in seconds",
    ["node"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    registry=REGISTRY,
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "token_type"],  # token_type: "input" | "output"
    registry=REGISTRY,
)

posts_published_total = Counter(
    "posts_published_total",
    "Total posts published to LinkedIn",
    ["dry_run"],
    registry=REGISTRY,
)

approval_queue_size = Gauge(
    "approval_queue_size",
    "Number of posts currently awaiting approval",
    registry=REGISTRY,
)

pipeline_errors_total = Counter(
    "pipeline_errors_total",
    "Total pipeline errors by node",
    ["node"],
    registry=REGISTRY,
)


def get_metrics_output() -> bytes:
    return generate_latest(REGISTRY)
