"""
Service for managing cached longest links analysis.

This service handles caching of expensive longest links calculations
to improve page load performance from 6-18 seconds to under 200ms.
"""

import json
import logging
import os
import time
from typing import Any

from psycopg2.extras import RealDictCursor

from ..database.connection import get_db_connection, put_db_connection

logger = logging.getLogger(__name__)


class LongestLinksCacheService:
    """Service for managing longest links cache."""

    # Cache TTL in seconds (default: 10 minutes, configurable via env var)
    CACHE_TTL_SECONDS = int(os.getenv("MALLA_LONGEST_LINKS_CACHE_TTL_SECONDS", "600"))

    @staticmethod
    def get_cached_result(
        min_distance_km: float = 1.0, min_snr: float = -20.0, max_results: int = 100
    ) -> dict[str, Any] | None:
        """
        Get cached longest links analysis if available and fresh.

        Args:
            min_distance_km: Minimum distance filter
            min_snr: Minimum SNR filter
            max_results: Maximum results

        Returns:
            Cached data dict or None if cache miss/expired
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Build parameters dict for matching
            parameters = {
                "min_distance_km": min_distance_km,
                "min_snr": min_snr,
                "max_results": max_results,
            }

            # Check for cached entry
            cursor.execute(
                """
                SELECT data, calculated_at
                FROM cached_longest_links
                WHERE parameters = %s::jsonb
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (json.dumps(parameters),),
            )

            row = cursor.fetchone()
            cursor.close()
            put_db_connection(conn)

            if not row:
                logger.debug(f"Cache miss for longest links (params: {parameters})")
                return None

            # Check if cache is still fresh
            calculated_at = row["calculated_at"]
            age_seconds = time.time() - calculated_at.timestamp()

            if age_seconds > LongestLinksCacheService.CACHE_TTL_SECONDS:
                logger.info(f"Cache expired ({age_seconds:.0f}s old) for longest links")
                return None

            logger.info(f"Cache hit for longest links (age: {age_seconds:.0f}s)")
            return row["data"]

        except Exception as e:
            logger.error(f"Error getting cached longest links: {e}")
            return None

    @staticmethod
    def store_cached_result(
        data: dict[str, Any],
        min_distance_km: float = 1.0,
        min_snr: float = -20.0,
        max_results: int = 100,
    ) -> bool:
        """
        Store longest links analysis results in cache.

        Args:
            data: Analysis results to cache
            min_distance_km: Minimum distance filter used
            min_snr: Minimum SNR filter used
            max_results: Maximum results used

        Returns:
            True if stored successfully, False otherwise
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            parameters = {
                "min_distance_km": min_distance_km,
                "min_snr": min_snr,
                "max_results": max_results,
            }

            # Insert or update cache entry
            cursor.execute(
                """
                INSERT INTO cached_longest_links (data, parameters, calculated_at)
                VALUES (%s::jsonb, %s::jsonb, NOW())
                ON CONFLICT (parameters)
                DO UPDATE SET
                    data = EXCLUDED.data,
                    calculated_at = NOW()
                """,
                (json.dumps(data), json.dumps(parameters)),
            )

            conn.commit()
            cursor.close()
            put_db_connection(conn)

            logger.info(f"Stored cached longest links (params: {parameters})")
            return True

        except Exception as e:
            logger.error(f"Error storing cached longest links: {e}")
            return False

    @staticmethod
    def clear_cache() -> bool:
        """
        Clear all cached longest links entries.

        Returns:
            True if cleared successfully, False otherwise
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM cached_longest_links")
            deleted_count = cursor.rowcount
            conn.commit()
            cursor.close()
            put_db_connection(conn)

            logger.info(f"Cleared {deleted_count} cached longest links entries")
            return True

        except Exception as e:
            logger.error(f"Error clearing cached longest links: {e}")
            return False
