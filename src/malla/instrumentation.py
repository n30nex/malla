"""
Instrumentation helpers for Meshtastic Mesh Health Web UI.
"""

import logging
import time

from flask import Blueprint, Response, g, request
from opentelemetry import trace

from .metrics import (
    API_REQUEST_DURATION,
    API_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
)

logger = logging.getLogger(__name__)
TRACER = trace.get_tracer(__name__)


def _endpoint_label() -> str:
    """Return a stable endpoint label for metrics."""
    if request.url_rule and request.url_rule.rule:
        return request.url_rule.rule
    if request.endpoint:
        return request.endpoint
    return request.path or "unknown"


def _before_request() -> None:
    """Record start time of request."""
    g.request_start_time = time.perf_counter()


def _after_request(response: Response) -> Response:
    """Record request metrics."""
    try:
        start_time = getattr(g, "request_start_time", None)
        if start_time is None:
            return response

        duration = time.perf_counter() - start_time
        endpoint = _endpoint_label()
        status_code = response.status_code
        status = "success" if status_code < 400 else "error"

        # Record generic HTTP metrics
        HTTP_REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(
            duration
        )
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status=status_code
        ).inc()

        # Record API-specific metrics if this is an API request
        # We consider it an API request if the path starts with /api
        # or if the blueprint name contains 'api'
        is_api = request.path.startswith("/api") or (
            request.blueprint and "api" in request.blueprint
        )

        if is_api:
            API_REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)
            API_REQUESTS_TOTAL.labels(endpoint=endpoint, status=status).inc()

    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Failed to record metrics: {exc}")
    return response


def _teardown_request(exc: Exception | None) -> None:
    """Ensure error responses still get counted."""
    if exc is None:
        return

    start_time = getattr(g, "request_start_time", None)
    if start_time is None:
        return

    try:
        duration = time.perf_counter() - start_time
        endpoint = _endpoint_label()

        HTTP_REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(
            duration
        )
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status=500
        ).inc()

        is_api = request.path.startswith("/api") or (
            request.blueprint and "api" in request.blueprint
        )

        if is_api:
            API_REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)
            API_REQUESTS_TOTAL.labels(endpoint=endpoint, status="error").inc()

    except Exception as metric_exc:  # noqa: BLE001
        logger.debug(f"Failed to record teardown metrics: {metric_exc}")


def register_metrics(blueprint: Blueprint) -> None:
    """Register metrics hooks on a blueprint."""
    blueprint.before_request(_before_request)
    blueprint.after_request(_after_request)
    blueprint.teardown_request(_teardown_request)
