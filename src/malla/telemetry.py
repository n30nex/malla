import logging
from typing import Optional

from flask import Flask
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def setup_telemetry(app: Optional[Flask], endpoint: str) -> None:
    """
    Configure OpenTelemetry tracing for the application.

    This sets up comprehensive instrumentation including:
    - Flask HTTP requests (if *app* is provided)
    - Psycopg2 database operations (default)
    - SQLite3 database operations (optional when using SQLite backend)
    - Python logging (with trace context injection)
    - HTTP client requests (via requests library)
    - System metrics (CPU, memory, etc.)

    Args:
        app: Optional Flask application instance.
        endpoint: The OTLP endpoint URL (e.g., "http://localhost:4317").
        use_sqlite: If True, also instrument sqlite3 (for test/local SQLite runs).
    """
    if not endpoint:
        logger.info("OTLP endpoint not configured, skipping telemetry setup")
        return

    logger.info(f"Setting up OpenTelemetry with OTLP endpoint: {endpoint}")

    # Create resource with service name
    resource = Resource(attributes={SERVICE_NAME: "malla-web" if app else "malla-capture"})

    # Setup trace provider
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # Instrument Flask application
    if app is not None:
        FlaskInstrumentor().instrument_app(app)
        logger.info("Flask instrumentation enabled")

    # Instrument database driver
    try:
        Psycopg2Instrumentor().instrument()
        logger.info("Psycopg2 instrumentation enabled")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not instrument psycopg2: {exc}")

    # Instrument logging to inject trace context into logs
    LoggingInstrumentor().instrument(set_logging_format=True)
    logger.info("Logging instrumentation enabled (trace context injection)")

    # Instrument requests library for HTTP client tracing
    RequestsInstrumentor().instrument()
    logger.info("Requests instrumentation enabled")

    # Instrument system metrics collection
    SystemMetricsInstrumentor().instrument()
    logger.info("System metrics instrumentation enabled")

    logger.info("OpenTelemetry instrumentation setup complete")
