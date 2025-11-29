"""
Prometheus metrics for the Malla web UI.

This module provides Prometheus metrics for monitoring web UI performance,
including database query timing, API endpoint response times, and request counts.
"""

import logging
from typing import Any

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry

logger = logging.getLogger(__name__)


def _get_existing_metric(name: str, metric_type):
    """Get existing metric from registry by name and type."""
    # Search through all collectors in the registry
    for collector in list(REGISTRY._collector_to_names.keys()):
        # Check if this is the right type and has the matching name
        if isinstance(collector, metric_type):
            if hasattr(collector, '_name') and collector._name == name:
                return collector
            # Also check the 'name' attribute
            if hasattr(collector, 'name') and collector.name == name:
                return collector
    # Try searching by the names in the mapping
    for collector, names in REGISTRY._collector_to_names.items():
        if isinstance(collector, metric_type) and name in names:
            return collector
    return None


# HTTP request metrics
try:
    HTTP_REQUESTS_TOTAL = Counter(
        "malla_http_requests_total",
        "Total number of HTTP requests",
        ["method", "endpoint", "status"],
    )
except ValueError as e:
    if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
        existing = _get_existing_metric("malla_http_requests_total", Counter)
        if existing:
            HTTP_REQUESTS_TOTAL = existing
            logger.debug("Reusing existing HTTP_REQUESTS_TOTAL metric")
        else:
            # If we can't find it, create with a different name to avoid conflict
            logger.warning("Could not find existing HTTP_REQUESTS_TOTAL, metrics may be duplicated")
            HTTP_REQUESTS_TOTAL = Counter(
                "malla_http_requests_total_alt",
                "Total number of HTTP requests (alt)",
                ["method", "endpoint", "status"],
            )
    else:
        raise

try:
    HTTP_REQUEST_DURATION = Histogram(
        "malla_http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "endpoint"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
except ValueError as e:
    if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
        existing = _get_existing_metric("malla_http_request_duration_seconds", Histogram)
        if existing:
            HTTP_REQUEST_DURATION = existing
            logger.debug("Reusing existing HTTP_REQUEST_DURATION metric")
        else:
            logger.warning("Could not find existing HTTP_REQUEST_DURATION, creating alternate")
            HTTP_REQUEST_DURATION = Histogram(
                "malla_http_request_duration_seconds_alt",
                "HTTP request duration in seconds (alt)",
                ["method", "endpoint"],
                buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            )
    else:
        raise

# Database query metrics
try:
    DB_QUERY_DURATION = Histogram(
        "malla_db_query_seconds",
        "Database query duration in seconds",
        ["operation", "table"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
except ValueError as e:
    if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
        existing = _get_existing_metric("malla_db_query_seconds", Histogram)
        if existing:
            DB_QUERY_DURATION = existing
            logger.debug("Reusing existing DB_QUERY_DURATION metric")
        else:
            logger.warning("Could not find existing DB_QUERY_DURATION, creating alternate")
            DB_QUERY_DURATION = Histogram(
                "malla_db_query_seconds_alt",
                "Database query duration in seconds (alt)",
                ["operation", "table"],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            )
    else:
        raise

try:
    DB_QUERY_COUNT = Counter(
        "malla_db_queries_total",
        "Total number of database queries",
        ["operation", "table", "status"],
    )
except ValueError as e:
    if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
        existing = _get_existing_metric("malla_db_queries_total", Counter)
        if existing:
            DB_QUERY_COUNT = existing
            logger.debug("Reusing existing DB_QUERY_COUNT metric")
        else:
            logger.warning("Could not find existing DB_QUERY_COUNT, creating alternate")
            DB_QUERY_COUNT = Counter(
                "malla_db_queries_total_alt",
                "Total number of database queries (alt)",
                ["operation", "table", "status"],
            )
    else:
        raise

# API endpoint metrics
try:
    API_REQUEST_DURATION = Histogram(
        "malla_api_request_duration_seconds",
        "API endpoint request duration in seconds",
        ["endpoint"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
except ValueError as e:
    if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
        existing = _get_existing_metric("malla_api_request_duration_seconds", Histogram)
        if existing:
            API_REQUEST_DURATION = existing
            logger.debug("Reusing existing API_REQUEST_DURATION metric")
        else:
            logger.warning("Could not find existing API_REQUEST_DURATION, creating alternate")
            API_REQUEST_DURATION = Histogram(
                "malla_api_request_duration_seconds_alt",
                "API endpoint request duration in seconds (alt)",
                ["endpoint"],
                buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            )
    else:
        raise

try:
    API_REQUESTS_TOTAL = Counter(
        "malla_api_requests_total",
        "Total number of API requests",
        ["endpoint", "status"],
    )
except ValueError as e:
    if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
        existing = _get_existing_metric("malla_api_requests_total", Counter)
        if existing:
            API_REQUESTS_TOTAL = existing
            logger.debug("Reusing existing API_REQUESTS_TOTAL metric")
        else:
            logger.warning("Could not find existing API_REQUESTS_TOTAL, creating alternate")
            API_REQUESTS_TOTAL = Counter(
                "malla_api_requests_total_alt",
                "Total number of API requests (alt)",
                ["endpoint", "status"],
            )
    else:
        raise


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest()


def get_metrics_content_type() -> str:
    """Get the content type for Prometheus metrics."""
    return CONTENT_TYPE_LATEST
