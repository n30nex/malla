"""
Prometheus metrics for the Malla web UI.

This module provides Prometheus metrics for monitoring web UI performance,
including database query timing, API endpoint response times, and request counts.
"""

import logging
import os
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

logger = logging.getLogger(__name__)

# Dedicated registry for this process; multiprocess collection is handled at scrape time.
_PROCESS_REGISTRY = CollectorRegistry()
_MULTIPROC_DIR = os.getenv("PROMETHEUS_MULTIPROC_DIR")


def _counter(name: str, documentation: str, labelnames: list[str]) -> Counter:
    return Counter(name, documentation, labelnames, registry=_PROCESS_REGISTRY)


def _histogram(
    name: str, documentation: str, labelnames: list[str], buckets: tuple[float, ...]
) -> Histogram:
    return Histogram(
        name,
        documentation,
        labelnames,
        buckets=buckets,
        registry=_PROCESS_REGISTRY,
    )


# HTTP request metrics
HTTP_REQUESTS_TOTAL = _counter(
    "malla_http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)
HTTP_REQUEST_DURATION = _histogram(
    "malla_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Database query metrics
DB_QUERY_DURATION = _histogram(
    "malla_db_query_seconds",
    "Database query duration in seconds",
    ["operation", "table"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
DB_QUERY_COUNT = _counter(
    "malla_db_queries_total",
    "Total number of database queries",
    ["operation", "table", "status"],
)

# API endpoint metrics
API_REQUEST_DURATION = _histogram(
    "malla_api_request_duration_seconds",
    "API endpoint request duration in seconds",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
API_REQUESTS_TOTAL = _counter(
    "malla_api_requests_total",
    "Total number of API requests",
    ["endpoint", "status"],
)


def _get_registry() -> CollectorRegistry:
    """Return the appropriate registry for scraping (multiprocess-aware)."""
    if _MULTIPROC_DIR:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return registry
    return _PROCESS_REGISTRY


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    registry = _get_registry()
    return generate_latest(registry)


def get_metrics_content_type() -> str:
    """Get the content type for Prometheus metrics."""
    return CONTENT_TYPE_LATEST
