"""
Shared logging helpers for consistent stdout/stderr routing.
"""

from __future__ import annotations

import logging
import sys
from typing import Iterable


class _StdoutFilter(logging.Filter):
    """Route records below WARNING to stdout handler."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        return record.levelno < logging.WARNING


def _coerce_level(level: str | int | None) -> int:
    """Convert string/integer log level inputs to a numeric level."""

    if isinstance(level, int):
        return level

    if isinstance(level, str):
        name = level.strip().upper()
        return logging._nameToLevel.get(name, logging.INFO)  # type: ignore[attr-defined]

    return logging.INFO


def setup_logging(level: str | int | None = None, extra_handlers: Iterable[logging.Handler] | None = None) -> None:
    """
    Configure root logging to send info/debug to stdout and warnings/errors to stderr.

    Args:
        level: Desired root log level (string like "INFO" or integer).
        extra_handlers: Optional additional handlers to attach.
    """

    # Enhanced formatter with optional trace/span context
    class StructuredFormatter(logging.Formatter):
        """Formatter that includes trace context when available."""

        def format(self, record: logging.LogRecord) -> str:
            # Add trace context if available (from OpenTelemetry)
            trace_id = getattr(record, "otelTraceID", None)
            span_id = getattr(record, "otelSpanID", None)

            if trace_id or span_id:
                context_parts = []
                if trace_id:
                    context_parts.append(f"trace_id={trace_id}")
                if span_id:
                    context_parts.append(f"span_id={span_id}")
                record.msg = f"[{' '.join(context_parts)}] {record.msg}"

            return super().format(record)

    formatter = StructuredFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_StdoutFilter())
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stdout_handler, stderr_handler]
    if extra_handlers:
        handlers.extend(extra_handlers)

    logging.basicConfig(
        level=_coerce_level(level),
        handlers=handlers,
        force=True,
    )
