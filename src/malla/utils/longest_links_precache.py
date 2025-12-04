"""
Background precaching service for longest links analysis.

This service periodically precaches longest links analysis results to ensure
fast page loads even when the cache has expired.
"""

import logging
import os
import threading
import time
from typing import Any

from ..services.longest_links_cache_service import LongestLinksCacheService
from ..services.traceroute_service import TracerouteService

logger = logging.getLogger(__name__)

# Control flags
_precache_stop = threading.Event()
_precache_thread: threading.Thread | None = None

# Default precache interval (configurable via env var, default: 5 minutes)
PRECACHE_INTERVAL_SECONDS = int(os.getenv("MALLA_LONGEST_LINKS_PRECACHE_INTERVAL", "300"))


def _precache_worker() -> None:
    """Background worker that periodically precaches longest links analysis."""
    logger.info(
        f"Longest links precache worker started (interval={PRECACHE_INTERVAL_SECONDS}s)"
    )

    # Default parameters to precache (most common use case)
    default_params = {
        "min_distance_km": 1.0,
        "min_snr": -200.0,
        "max_results": 100,
    }

    while not _precache_stop.is_set():
        try:
            # Check if cache is fresh or needs refresh
            cached = LongestLinksCacheService.get_cached_result(**default_params)
            if cached:
                logger.debug("Longest links cache is fresh, skipping precache")
            else:
                logger.info("Precaching longest links analysis...")
                start_time = time.time()
                try:
                    # Perform the analysis (will be cached automatically)
                    result = TracerouteService.get_longest_links_analysis(**default_params)
                    duration = time.time() - start_time
                    logger.info(
                        f"Longest links precache completed in {duration:.2f}s "
                        f"(direct: {len(result.get('direct_links', []))}, "
                        f"indirect: {len(result.get('indirect_links', []))})"
                    )
                except Exception as e:
                    logger.error(f"Error during longest links precache: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error in precache worker: {e}", exc_info=True)

        # Wait for interval or stop signal
        if _precache_stop.wait(timeout=PRECACHE_INTERVAL_SECONDS):
            break

    logger.info("Longest links precache worker stopped")


def start_precache() -> None:
    """Start the background precache worker thread."""
    global _precache_thread

    if _precache_thread is not None and _precache_thread.is_alive():
        logger.warning("Precache thread already running")
        return

    _precache_stop.clear()
    _precache_thread = threading.Thread(target=_precache_worker, daemon=True, name="LongestLinksPrecache")
    _precache_thread.start()
    logger.info("Started longest links precache background thread")


def stop_precache() -> None:
    """Stop the background precache worker thread."""
    global _precache_thread

    if _precache_thread is None:
        return

    _precache_stop.set()
    if _precache_thread.is_alive():
        _precache_thread.join(timeout=5.0)
    _precache_thread = None
    logger.info("Stopped longest links precache background thread")




