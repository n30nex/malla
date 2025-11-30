"""
Centralized cache manager for node/gateway lookups with TTL and refresh strategies.

This module provides a unified caching interface that can be used across services
to reduce repeated database lookups and improve performance.
"""

import logging
import threading
import time
from typing import Any, Callable, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheEntry(Generic[T]):
    """Represents a cached value with metadata."""

    def __init__(self, value: T, timestamp: float, ttl_seconds: float):
        self.value = value
        self.timestamp = timestamp
        self.ttl_seconds = ttl_seconds
        self.access_count = 0
        self.last_access = timestamp

    def is_expired(self, now: float | None = None) -> bool:
        """Check if the cache entry has expired."""
        if now is None:
            now = time.time()
        return (now - self.timestamp) >= self.ttl_seconds

    def is_stale(self, stale_threshold: float, now: float | None = None) -> bool:
        """Check if the cache entry is stale (approaching expiration)."""
        if now is None:
            now = time.time()
        age = now - self.timestamp
        return age >= (self.ttl_seconds * stale_threshold)

    def touch(self) -> None:
        """Update access metadata."""
        self.access_count += 1
        self.last_access = time.time()


class CacheManager(Generic[T]):
    """
    Centralized cache manager with TTL, refresh strategies, and automatic cleanup.

    Features:
    - TTL-based expiration
    - Stale-while-revalidate pattern (optional)
    - Automatic cache size management (LRU eviction)
    - Thread-safe operations
    - Background refresh for frequently accessed items
    """

    def __init__(
        self,
        default_ttl_seconds: float = 300.0,  # 5 minutes default
        max_size: int = 10000,
        stale_threshold: float = 0.8,  # Consider stale at 80% of TTL
        enable_background_refresh: bool = True,
        refresh_interval_seconds: float = 60.0,
    ):
        """
        Initialize the cache manager.

        Args:
            default_ttl_seconds: Default TTL for cache entries
            max_size: Maximum number of entries before LRU eviction
            stale_threshold: Fraction of TTL at which entries are considered stale
            enable_background_refresh: Enable background refresh of stale entries
            refresh_interval_seconds: How often to check for stale entries to refresh
        """
        self._cache: dict[str, CacheEntry[T]] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size
        self._stale_threshold = stale_threshold
        self._enable_background_refresh = enable_background_refresh
        self._refresh_interval = refresh_interval_seconds
        self._refresh_callbacks: dict[str, Callable[[], T]] = {}
        self._stop_refresh = threading.Event()
        self._refresh_thread: threading.Thread | None = None

        if enable_background_refresh:
            self._start_refresh_thread()

    def _start_refresh_thread(self) -> None:
        """Start background thread for refreshing stale entries."""
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            return

        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_worker, name="CacheRefreshWorker", daemon=True
        )
        self._refresh_thread.start()
        logger.debug("Cache refresh thread started")

    def _refresh_worker(self) -> None:
        """Background worker that refreshes stale cache entries."""
        while not self._stop_refresh.wait(self._refresh_interval):
            try:
                self._refresh_stale_entries()
            except Exception as e:
                logger.warning(f"Error in cache refresh worker: {e}")

    def _refresh_stale_entries(self) -> None:
        """Refresh stale cache entries that have refresh callbacks."""
        now = time.time()
        stale_keys = []

        with self._lock:
            for key, entry in self._cache.items():
                if (
                    entry.is_stale(self._stale_threshold, now)
                    and key in self._refresh_callbacks
                ):
                    stale_keys.append(key)

        # Refresh stale entries (outside lock to avoid blocking)
        for key in stale_keys:
            try:
                callback = self._refresh_callbacks.get(key)
                if callback:
                    new_value = callback()
                    self.set(key, new_value, ttl_seconds=None)  # Use existing TTL
                    logger.debug(f"Refreshed stale cache entry: {key}")
            except Exception as e:
                logger.warning(f"Error refreshing cache entry {key}: {e}")

    def get(
        self,
        key: str,
        default: T | None = None,
        refresh_callback: Callable[[], T] | None = None,
    ) -> T | None:
        """
        Get a value from the cache.

        Args:
            key: Cache key
            default: Default value if key not found
            refresh_callback: Optional callback to refresh the value if stale

        Returns:
            Cached value or default
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                return default

            # Check if expired
            if entry.is_expired():
                # Remove expired entry
                del self._cache[key]
                if key in self._refresh_callbacks:
                    del self._refresh_callbacks[key]
                return default

            # Touch the entry (update access metadata)
            entry.touch()

            # If stale and refresh callback provided, trigger refresh (async)
            if entry.is_stale(self._stale_threshold) and refresh_callback:
                # Store callback for background refresh
                self._refresh_callbacks[key] = refresh_callback
                # Return stale value immediately (stale-while-revalidate pattern)
                logger.debug(f"Returning stale cache entry (will refresh): {key}")

            return entry.value

    def set(
        self,
        key: str,
        value: T,
        ttl_seconds: float | None = None,
        refresh_callback: Callable[[], T] | None = None,
    ) -> None:
        """
        Set a value in the cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: TTL in seconds (uses default if None)
            refresh_callback: Optional callback to refresh the value when stale
        """
        if ttl_seconds is None:
            ttl_seconds = self._default_ttl

        with self._lock:
            # Evict LRU entries if cache is full
            if len(self._cache) >= self._max_size and key not in self._cache:
                self._evict_lru()

            entry = CacheEntry(value, time.time(), ttl_seconds)
            self._cache[key] = entry

            if refresh_callback:
                self._refresh_callbacks[key] = refresh_callback

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._cache:
            return

        # Find LRU entry (lowest last_access time)
        lru_key = min(
            self._cache.keys(), key=lambda k: self._cache[k].last_access
        )
        del self._cache[lru_key]
        if lru_key in self._refresh_callbacks:
            del self._refresh_callbacks[lru_key]
        logger.debug(f"Evicted LRU cache entry: {lru_key}")

    def delete(self, key: str) -> None:
        """Delete a key from the cache."""
        with self._lock:
            self._cache.pop(key, None)
            self._refresh_callbacks.pop(key, None)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._refresh_callbacks.clear()

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], T],
        ttl_seconds: float | None = None,
        refresh_callback: Callable[[], T] | None = None,
    ) -> T:
        """
        Get a value from cache, or set it using factory if not found.

        Args:
            key: Cache key
            factory: Callable that returns the value to cache
            ttl_seconds: TTL in seconds (uses default if None)
            refresh_callback: Optional callback to refresh the value when stale

        Returns:
            Cached or newly created value
        """
        value = self.get(key, refresh_callback=refresh_callback)
        if value is None:
            value = factory()
            self.set(key, value, ttl_seconds=ttl_seconds, refresh_callback=refresh_callback)
        return value

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_entries = len(self._cache)
            total_access = sum(entry.access_count for entry in self._cache.values())
            now = time.time()
            expired_count = sum(
                1 for entry in self._cache.values() if entry.is_expired(now)
            )
            stale_count = sum(
                1
                for entry in self._cache.values()
                if entry.is_stale(self._stale_threshold, now)
            )

            return {
                "total_entries": total_entries,
                "max_size": self._max_size,
                "total_accesses": total_access,
                "expired_entries": expired_count,
                "stale_entries": stale_count,
                "refresh_callbacks": len(self._refresh_callbacks),
            }

    def shutdown(self) -> None:
        """Shutdown the cache manager and stop background threads."""
        self._stop_refresh.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=2.0)
        self.clear()
        logger.debug("Cache manager shut down")


# Global cache manager instances for different use cases
_node_cache_manager: CacheManager[Any] | None = None
_gateway_cache_manager: CacheManager[Any] | None = None


def get_node_cache_manager() -> CacheManager[Any]:
    """Get or create the global node cache manager."""
    global _node_cache_manager
    if _node_cache_manager is None:
        _node_cache_manager = CacheManager(
            default_ttl_seconds=300.0,  # 5 minutes
            max_size=50000,  # Large cache for nodes
            enable_background_refresh=True,
        )
    return _node_cache_manager


def get_gateway_cache_manager() -> CacheManager[Any]:
    """Get or create the global gateway cache manager."""
    global _gateway_cache_manager
    if _gateway_cache_manager is None:
        _gateway_cache_manager = CacheManager(
            default_ttl_seconds=300.0,  # 5 minutes
            max_size=1000,  # Smaller cache for gateway stats
            enable_background_refresh=True,
        )
    return _gateway_cache_manager


def shutdown_cache_managers() -> None:
    """Shutdown all cache managers (for cleanup)."""
    global _node_cache_manager, _gateway_cache_manager
    if _node_cache_manager:
        _node_cache_manager.shutdown()
        _node_cache_manager = None
    if _gateway_cache_manager:
        _gateway_cache_manager.shutdown()
        _gateway_cache_manager = None
