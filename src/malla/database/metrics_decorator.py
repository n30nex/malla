"""
Decorator for tracking database query performance metrics.

This module provides decorators to instrument repository methods with
Prometheus metrics for query timing and counts.
"""

import functools
import logging
import time
from collections.abc import Callable
from typing import Any

from ..metrics import DB_QUERY_COUNT, DB_QUERY_DURATION

logger = logging.getLogger(__name__)


def track_query_time(operation: str, table: str = "unknown"):
    """
    Decorator to track database query execution time and count.

    Records metrics to Prometheus for monitoring database performance.

    Args:
        operation: Type of database operation (e.g., "select", "insert", "update")
        table: Name of the primary table being queried

    Example:
        @track_query_time("select", "packet_history")
        def get_packets(self, limit: int = 100):
            # ... database query code ...
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            status = "success"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                DB_QUERY_DURATION.labels(operation=operation, table=table).observe(
                    duration
                )
                DB_QUERY_COUNT.labels(
                    operation=operation, table=table, status=status
                ).inc()
                logger.debug(
                    f"Query {operation} on {table}: {duration:.3f}s ({status})"
                )

        return wrapper

    return decorator
