"""
Caching utilities for query results and frequently accessed data.

This module provides caching mechanisms to improve performance by
reducing database queries for frequently accessed data.
"""

import functools
import hashlib
import json
import logging
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Simple in-memory cache with TTL
_cache: dict[str, tuple[Any, float]] = {}
_cache_lock = None


def _get_cache_lock():
    """Lazy import threading lock to avoid circular imports."""
    global _cache_lock
    if _cache_lock is None:
        import threading

        _cache_lock = threading.Lock()
    return _cache_lock


def cache_result(ttl_seconds: int = 60, max_size: int = 1000):
    """Decorator to cache function results with TTL.

    Args:
        ttl_seconds: Time to live for cached results in seconds
        max_size: Maximum number of cached entries

    Returns:
        Decorated function with caching
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Create cache key from function name and arguments
            cache_key_data = {
                "func": func.__name__,
                "args": str(args),
                "kwargs": json.dumps(kwargs, sort_keys=True, default=str),
            }
            cache_key = hashlib.md5(
                json.dumps(cache_key_data, sort_keys=True).encode()
            ).hexdigest()

            lock = _get_cache_lock()
            current_time = time.time()

            # Check cache
            with lock:
                if cache_key in _cache:
                    result, expiry_time = _cache[cache_key]
                    if current_time < expiry_time:
                        logger.debug(f"Cache hit for {func.__name__}")
                        return result
                    else:
                        # Expired, remove it
                        del _cache[cache_key]

                # Cache miss or expired - call function
                result = func(*args, **kwargs)

                # Store in cache
                if len(_cache) >= max_size:
                    # Remove oldest entry (simple FIFO)
                    oldest_key = min(_cache.keys(), key=lambda k: _cache[k][1])
                    del _cache[oldest_key]

                _cache[cache_key] = (result, current_time + ttl_seconds)
                logger.debug(f"Cached result for {func.__name__} (TTL: {ttl_seconds}s)")

            return result

        return wrapper

    return decorator


def clear_cache(pattern: str | None = None) -> int:
    """Clear cache entries matching a pattern.

    Args:
        pattern: Optional pattern to match function names. If None, clears all.

    Returns:
        Number of entries cleared
    """
    lock = _get_cache_lock()
    with lock:
        if pattern is None:
            count = len(_cache)
            _cache.clear()
            return count

        # Clear entries matching pattern
        keys_to_remove = [
            k for k in _cache.keys() if pattern in k  # Simple string matching
        ]
        for key in keys_to_remove:
            del _cache[key]
        return len(keys_to_remove)


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics.

    Returns:
        Dictionary with cache statistics
    """
    lock = _get_cache_lock()
    with lock:
        current_time = time.time()
        valid_entries = sum(1 for _, expiry in _cache.values() if current_time < expiry)
        expired_entries = len(_cache) - valid_entries

        return {
            "total_entries": len(_cache),
            "valid_entries": valid_entries,
            "expired_entries": expired_entries,
        }
