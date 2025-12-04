"""
Analytics service for Meshtastic Mesh Health Web UI
"""

import logging
import time
from collections import defaultdict
from typing import Any

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# NOTE: Lightweight, in-process cache so that repeated calls in a short period
# do not hit the database multiple times. This is intentionally simple to keep
# dependencies minimal; for a multi-process deployment a proper cache (e.g.
# Redis) should be used instead.


class AnalyticsService:
    """Service for analytics and statistical calculations."""

    # (gateway_id, from_node, hop_count) → (timestamp, data)
    _CACHE: dict[
        tuple[str | None, int | None, int | None], tuple[float, dict[str, Any]]
    ] = {}
    _CACHE_TTL_SEC: int = 60  # one minute cache window

    @staticmethod
    def get_analytics_data(
        gateway_id: str | None = None,
        from_node: int | None = None,
        hop_count: int | None = None,
        hours: int = 24,
    ) -> dict[str, Any]:
        """Get comprehensive analytics data for the dashboard with simple in-memory caching."""

        # Normalize hours to a sane range (1 hour to 7 days)
        if hours < 1:
            hours = 1
        if hours > 24 * 7:
            hours = 24 * 7

        cache_key = (gateway_id, from_node, hop_count, hours)
        now_ts = time.time()

        # Return cached value if still valid
        cached = AnalyticsService._CACHE.get(cache_key)
        if cached and (now_ts - cached[0] < AnalyticsService._CACHE_TTL_SEC):
            return cached[1]

        logger.info(
            "Computing analytics data (cache miss): gateway_id=%s, from_node=%s, hop_count=%s",
            gateway_id,
            from_node,
            hop_count,
        )

        try:
            # Build filters object
            filters: dict[str, Any] = {}
            if gateway_id:
                filters["gateway_id"] = gateway_id
            if from_node:
                filters["from_node"] = from_node
            if hop_count is not None:
                filters["hop_count"] = hop_count

            since_timestamp = now_ts - hours * 3600
            seven_days_ago = now_ts - 7 * 24 * 3600

            packet_stats = AnalyticsService._get_packet_statistics(
                filters, since_timestamp
            )
            node_stats = AnalyticsService._get_node_activity_statistics(
                filters, since_timestamp
            )
            signal_stats = AnalyticsService._get_signal_quality_statistics(
                filters, since_timestamp
            )
            temporal_stats = AnalyticsService._get_temporal_patterns(
                filters, since_timestamp
            )
            top_nodes = AnalyticsService._get_top_active_nodes(filters, seven_days_ago)
            packet_types = AnalyticsService._get_packet_type_distribution(
                filters, since_timestamp
            )
            gateway_stats = AnalyticsService._get_gateway_distribution(
                filters, since_timestamp
            )

            result = {
                "packet_statistics": packet_stats,
                "node_statistics": node_stats,
                "signal_quality": signal_stats,
                "temporal_patterns": temporal_stats,
                "top_nodes": top_nodes,
                "packet_types": packet_types,
                "gateway_distribution": gateway_stats,
            }

            # Save to cache
            AnalyticsService._CACHE[cache_key] = (now_ts, result)

            logger.info("Analytics data computed successfully (cached)")
            return result

        except Exception as e:
            logger.error(f"Error getting analytics data: {e}")
            raise

    @staticmethod
    def _get_packet_statistics(filters: dict, since_timestamp: float) -> dict[str, Any]:
        """Get basic packet statistics using optimized SQL query."""
        from ..database.connection import get_db_connection, put_db_connection

        # Build WHERE clause using psycopg2-style placeholders
        where_conditions: list[str] = ["timestamp >= %s"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = %s")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = %s")
            params.append(filters["from_node"])

        if filters.get("hop_count") is not None:
            where_conditions.append("(hop_start - hop_limit) = %s")
            params.append(filters["hop_count"])

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                COUNT(*) as total_packets,
                SUM(CASE WHEN processed_successfully THEN 1 ELSE 0 END) as successful_packets,
                AVG(CASE WHEN payload_length IS NOT NULL AND payload_length > 0 THEN payload_length END) as avg_payload_size
            FROM packet_history
            WHERE {where_clause}
        """

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            row = cursor.fetchone()
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        total_packets = row["total_packets"] or 0
        successful_packets = row["successful_packets"] or 0
        success_rate = (
            (successful_packets / total_packets * 100) if total_packets > 0 else 0
        )

        return {
            "total_packets": total_packets,
            "successful_packets": successful_packets,
            "failed_packets": total_packets - successful_packets,
            "success_rate": round(success_rate, 2),
            "average_payload_size": round(row["avg_payload_size"] or 0, 2),
        }

    @staticmethod
    def _get_node_activity_statistics(
        filters: dict, since_timestamp: float
    ) -> dict[str, Any]:
        """Get node activity statistics using optimized SQL query."""
        from ..database.connection import get_db_connection, put_db_connection

        conn = None
        cursor = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get total node count
            cursor.execute("SELECT COUNT(*) as total_nodes FROM node_info")
            total_nodes = cursor.fetchone()["total_nodes"]

            # Build WHERE clause for packet filtering
            where_conditions: list[str] = ["timestamp >= %s"]
            params: list[Any] = [since_timestamp]

            if filters.get("gateway_id"):
                where_conditions.append("gateway_id = %s")
                params.append(filters["gateway_id"])

            where_clause = " AND ".join(where_conditions)

            # Get node activity distribution using SQL aggregation
            cursor.execute(
                f"""
                WITH node_activity AS (
                    SELECT
                        from_node_id,
                        COUNT(*) as packet_count
                    FROM packet_history
                    WHERE from_node_id IS NOT NULL AND {where_clause}
                    GROUP BY from_node_id
                )
                SELECT
                    COUNT(*) as active_nodes,
                    SUM(CASE WHEN packet_count > 100 THEN 1 ELSE 0 END) as very_active,
                    SUM(CASE WHEN packet_count > 10 AND packet_count <= 100 THEN 1 ELSE 0 END) as moderately_active,
                    SUM(CASE WHEN packet_count >= 1 AND packet_count <= 10 THEN 1 ELSE 0 END) as lightly_active
                FROM node_activity
            """,
                params,
            )

            activity_row = cursor.fetchone()
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        active_nodes = activity_row["active_nodes"] or 0
        inactive_nodes = total_nodes - active_nodes

        activity_ranges = {
            "very_active": activity_row["very_active"] or 0,
            "moderately_active": activity_row["moderately_active"] or 0,
            "lightly_active": activity_row["lightly_active"] or 0,
            "inactive": inactive_nodes,
        }

        return {
            "total_nodes": total_nodes,
            "active_nodes": active_nodes,
            "inactive_nodes": inactive_nodes,
            "activity_rate": round((active_nodes / total_nodes * 100), 2)
            if total_nodes > 0
            else 0,
            "activity_distribution": activity_ranges,
        }

    @staticmethod
    def _get_signal_quality_statistics(
        filters: dict, since_timestamp: float
    ) -> dict[str, Any]:
        """Get signal quality statistics using optimized SQL query."""
        from ..database.connection import get_db_connection, put_db_connection

        # Build WHERE clause
        where_conditions: list[str] = ["timestamp >= %s"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = %s")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = %s")
            params.append(filters["from_node"])

        where_clause = " AND ".join(where_conditions)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get signal statistics using SQL aggregation
            cursor.execute(
                f"""
                SELECT
                    AVG(CASE WHEN rssi IS NOT NULL AND rssi != 0 THEN rssi END) as avg_rssi,
                    AVG(CASE WHEN snr IS NOT NULL THEN snr END) as avg_snr,
                    COUNT(CASE WHEN rssi IS NOT NULL AND rssi != 0 THEN 1 END) as rssi_count,
                    COUNT(CASE WHEN snr IS NOT NULL THEN 1 END) as snr_count,
                    -- RSSI distribution
                    SUM(CASE WHEN rssi > -70 THEN 1 ELSE 0 END) as rssi_excellent,
                    SUM(CASE WHEN rssi > -80 AND rssi <= -70 THEN 1 ELSE 0 END) as rssi_good,
                    SUM(CASE WHEN rssi > -90 AND rssi <= -80 THEN 1 ELSE 0 END) as rssi_fair,
                    SUM(CASE WHEN rssi <= -90 THEN 1 ELSE 0 END) as rssi_poor,
                    -- SNR distribution
                    SUM(CASE WHEN snr > 10 THEN 1 ELSE 0 END) as snr_excellent,
                    SUM(CASE WHEN snr > 5 AND snr <= 10 THEN 1 ELSE 0 END) as snr_good,
                    SUM(CASE WHEN snr > 0 AND snr <= 5 THEN 1 ELSE 0 END) as snr_fair,
                    SUM(CASE WHEN snr <= 0 THEN 1 ELSE 0 END) as snr_poor
                FROM packet_history
                WHERE {where_clause}
            """,
                params,
            )

            row = cursor.fetchone()
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        if not row or (row["rssi_count"] == 0 and row["snr_count"] == 0):
            return {
                "avg_rssi": None,
                "avg_snr": None,
                "rssi_distribution": {},
                "snr_distribution": {},
                "total_measurements": 0,
            }

        rssi_distribution = {
            "excellent": row["rssi_excellent"] or 0,
            "good": row["rssi_good"] or 0,
            "fair": row["rssi_fair"] or 0,
            "poor": row["rssi_poor"] or 0,
        }

        snr_distribution = {
            "excellent": row["snr_excellent"] or 0,
            "good": row["snr_good"] or 0,
            "fair": row["snr_fair"] or 0,
            "poor": row["snr_poor"] or 0,
        }

        return {
            "avg_rssi": round(row["avg_rssi"], 2) if row["avg_rssi"] else None,
            "avg_snr": round(row["avg_snr"], 2) if row["avg_snr"] else None,
            "rssi_distribution": rssi_distribution,
            "snr_distribution": snr_distribution,
            "total_measurements": max(row["rssi_count"] or 0, row["snr_count"] or 0),
        }

    @staticmethod
    def _get_temporal_patterns(filters: dict, since_timestamp: float) -> dict[str, Any]:
        """Get temporal patterns (hourly breakdown) efficiently using SQL aggregation."""

        from ..database.connection import get_db_connection, put_db_connection

        # Build WHERE clause similarly to PacketRepository but simplified (only params we care about)
        where_conditions: list[str] = ["timestamp >= %s"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = %s")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = %s")
            params.append(filters["from_node"])

        if filters.get("hop_count") is not None:
            where_conditions.append("(hop_start - hop_limit) = %s")
            params.append(filters["hop_count"])

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                to_char(to_timestamp(timestamp), 'HH24') AS hour,
                COUNT(*) AS total_packets,
                SUM(CASE WHEN processed_successfully = TRUE THEN 1 ELSE 0 END) AS successful_packets
            FROM packet_history
            WHERE {where_clause}
            GROUP BY hour
        """

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)

            rows = cursor.fetchall()
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        hourly_counts: dict[int, int] = defaultdict(int)
        hourly_success: dict[int, int] = defaultdict(int)

        for row in rows:
            hour = int(row["hour"])
            hourly_counts[hour] = row["total_packets"]
            hourly_success[hour] = row["successful_packets"]

        hourly_data: list[dict[str, Any]] = []
        for hour in range(24):
            count = hourly_counts.get(hour, 0)
            success = hourly_success.get(hour, 0)
            success_rate = (success / count * 100) if count > 0 else 0

            hourly_data.append(
                {
                    "hour": hour,
                    "total_packets": count,
                    "successful_packets": success,
                    "success_rate": round(success_rate, 2),
                }
            )

        # Determine peak and quiet hours if any packets exist
        peak_hour = (
            max(hourly_counts, key=lambda x: hourly_counts[x])
            if hourly_counts
            else None
        )
        quiet_hour = (
            min(hourly_counts, key=lambda x: hourly_counts[x])
            if hourly_counts
            else None
        )

        return {
            "hourly_breakdown": hourly_data,
            "peak_hour": peak_hour,
            "quiet_hour": quiet_hour,
        }

    @staticmethod
    def _get_top_active_nodes(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get top active nodes by packet count."""
        from ..database.connection import get_db_connection, put_db_connection

        conn = None
        cursor = None
        try:
            where_conditions: list[str] = [
                "ph.timestamp >= %s",
                "ph.from_node_id IS NOT NULL",
            ]
            params: list[Any] = [since_timestamp]

            if filters.get("gateway_id"):
                where_conditions.append("ph.gateway_id = %s")
                params.append(filters["gateway_id"])

            where_clause = " AND ".join(where_conditions)

            query = f"""
                SELECT
                    ph.from_node_id AS node_id,
                    MAX(ni.long_name) AS long_name,
                    MAX(ni.short_name) AS short_name,
                    MAX(ni.hw_model) AS hw_model,
                    COUNT(*) AS packet_count,
                    AVG(CAST(ph.rssi AS FLOAT)) AS avg_rssi,
                    AVG(CAST(ph.snr AS FLOAT)) AS avg_snr,
                    MAX(ph.timestamp) AS last_seen
                FROM packet_history ph
                LEFT JOIN node_info ni ON ph.from_node_id = ni.node_id
                WHERE {where_clause}
                GROUP BY ph.from_node_id
                HAVING COUNT(*) > 0
                ORDER BY packet_count DESC
                LIMIT 10
            """

            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            rows = cursor.fetchall() or []
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        top_nodes: list[dict[str, Any]] = []
        for row in rows:
            node_id = row.get("node_id")
            display_name = row.get("long_name") or row.get("short_name")
            if not display_name and node_id is not None:
                display_name = f"!{node_id:08x}"
            top_nodes.append(
                {
                    "node_id": node_id,
                    "display_name": display_name,
                    "packet_count": row.get("packet_count", 0) or 0,
                    "avg_rssi": row.get("avg_rssi"),
                    "avg_snr": row.get("avg_snr"),
                    "last_seen": row.get("last_seen"),
                    "hw_model": row.get("hw_model"),
                }
            )

        return top_nodes

    @staticmethod
    def _get_node_rankings(
        filters: dict, since_timestamp: float, order: str = "DESC", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get ranked nodes by packet count (hottest or coldest)."""
        from ..database.connection import get_db_connection, put_db_connection

        conn = None
        cursor = None
        try:
            where_conditions: list[str] = [
                "ph.timestamp >= %s",
                "ph.from_node_id IS NOT NULL",
            ]
            params: list[Any] = [since_timestamp]

            if filters.get("gateway_id"):
                where_conditions.append("ph.gateway_id = %s")
                params.append(filters["gateway_id"])

            where_clause = " AND ".join(where_conditions)

            # For "coldest", we still want active nodes (count > 0), just the ones with fewest packets
            query = f"""
                SELECT
                    ph.from_node_id AS node_id,
                    MAX(ni.long_name) AS long_name,
                    MAX(ni.short_name) AS short_name,
                    MAX(ni.hw_model) AS hw_model,
                    COUNT(*) AS packet_count,
                    AVG(CAST(ph.rssi AS FLOAT)) AS avg_rssi,
                    AVG(CAST(ph.snr AS FLOAT)) AS avg_snr,
                    MAX(ph.timestamp) AS last_seen
                FROM packet_history ph
                LEFT JOIN node_info ni ON ph.from_node_id = ni.node_id
                WHERE {where_clause}
                GROUP BY ph.from_node_id
                HAVING COUNT(*) > 0
                ORDER BY packet_count {order}
                LIMIT %s
            """

            params.append(limit)

            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            rows = cursor.fetchall() or []
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        ranked_nodes: list[dict[str, Any]] = []
        for row in rows:
            node_id = row.get("node_id")
            display_name = row.get("long_name") or row.get("short_name")
            if not display_name and node_id is not None:
                display_name = f"!{node_id:08x}"
            ranked_nodes.append(
                {
                    "node_id": node_id,
                    "display_name": display_name,
                    "packet_count": row.get("packet_count", 0) or 0,
                    "avg_rssi": row.get("avg_rssi"),
                    "avg_snr": row.get("avg_snr"),
                    "last_seen": row.get("last_seen"),
                    "hw_model": row.get("hw_model"),
                }
            )

        return ranked_nodes

    @staticmethod
    def _get_node_temperature_rankings(
        filters: dict, since_timestamp: float, order: str = "DESC", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get ranked nodes by temperature telemetry (hottest or coldest).

        Preference order:
        1. Use node_telemetry_latest if it has any recent rows.
        2. Fallback to decoding TELEMETRY_APP packets from packet_history.
        """
        from ..database.connection import get_db_connection, put_db_connection

        conn = None
        cursor = None
        ranked_nodes: list[dict[str, Any]] = []

        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # First try node_telemetry_latest for recent data
            # Convert Unix timestamp to PostgreSQL timestamp for comparison
            where_clauses: list[str] = ["ntl.last_updated >= to_timestamp(%s)"]
            params: list[Any] = [since_timestamp]

            if filters.get("gateway_id"):
                # Join packet_history to infer gateway for latest samples
                where_clauses.append(
                    "EXISTS (SELECT 1 FROM packet_history ph "
                    "WHERE ph.from_node_id = ntl.node_id "
                    "AND ph.gateway_id = %s "
                    "AND ph.timestamp >= %s)"
                )
                params.extend([filters["gateway_id"], since_timestamp])

            where_sql = " AND ".join(where_clauses)

            cursor.execute(
                f"""
                SELECT
                    ntl.node_id,
                    ntl.temperature,
                    ntl.last_updated,
                    ni.long_name,
                    ni.short_name,
                    ni.hw_model
                FROM node_telemetry_latest ntl
                LEFT JOIN node_info ni ON ntl.node_id = ni.node_id
                WHERE {where_sql} AND ntl.temperature IS NOT NULL
                ORDER BY ntl.temperature {"DESC" if order == "DESC" else "ASC"}
                LIMIT %s
                """,
                (*params, limit),
            )
            rows = cursor.fetchall() or []

            if rows:
                for row in rows:
                    node_id = row.get("node_id")
                    if node_id is None:
                        continue
                    display_name = row.get("long_name") or row.get("short_name")
                    if not display_name:
                        display_name = f"!{node_id:08x}"
                    ranked_nodes.append(
                        {
                            "node_id": node_id,
                            "display_name": display_name,
                            "temperature": round(row.get("temperature") or 0.0, 1),
                            "temperature_count": 1,
                            "hw_model": row.get("hw_model"),
                        }
                    )
                return ranked_nodes

            # Fallback: decode telemetry from packet_history as before
            try:
                from meshtastic import telemetry_pb2
            except ImportError:
                logger.warning(
                    "meshtastic protobuf not available, cannot decode telemetry"
                )
                return []

            where_conditions: list[str] = [
                "ph.timestamp >= %s",
                "ph.from_node_id IS NOT NULL",
                "ph.portnum_name = 'TELEMETRY_APP'",
                "ph.raw_payload IS NOT NULL",
            ]
            params = [since_timestamp]

            if filters.get("gateway_id"):
                where_conditions.append("ph.gateway_id = %s")
                params.append(filters["gateway_id"])

            where_clause = " AND ".join(where_conditions)

            query = f"""
                SELECT
                    ph.from_node_id AS node_id,
                    ph.raw_payload,
                    ph.timestamp,
                    MAX(ni.long_name) AS long_name,
                    MAX(ni.short_name) AS short_name,
                    MAX(ni.hw_model) AS hw_model
                FROM packet_history ph
                LEFT JOIN node_info ni ON ph.from_node_id = ni.node_id
                WHERE {where_clause}
                GROUP BY ph.from_node_id, ph.raw_payload, ph.timestamp
                ORDER BY ph.timestamp DESC
            """

            cursor.execute(query, params)
            rows = cursor.fetchall() or []

            logger.info(f"Temperature rankings: Fetched {len(rows)} telemetry packets")

            node_temperatures: dict[int, list[float]] = {}
            node_info: dict[int, dict[str, Any]] = {}
            decode_success_count = 0
            decode_fail_count = 0
            temperature_found_count = 0

            for row in rows:
                node_id = row.get("node_id")
                if not node_id:
                    continue

                if node_id not in node_info:
                    node_info[node_id] = {
                        "long_name": row.get("long_name"),
                        "short_name": row.get("short_name"),
                        "hw_model": row.get("hw_model"),
                    }

                raw_payload = row.get("raw_payload")
                if not raw_payload:
                    continue

                try:
                    # Convert memoryview to bytes if needed
                    if isinstance(raw_payload, memoryview):
                        raw_payload = bytes(raw_payload)
                    elif not isinstance(raw_payload, bytes):
                        continue

                    telemetry = telemetry_pb2.Telemetry()
                    telemetry.ParseFromString(raw_payload)
                    decode_success_count += 1

                    if telemetry.HasField("environment_metrics"):
                        env_metrics = telemetry.environment_metrics
                        if env_metrics.HasField("temperature"):
                            temp = env_metrics.temperature
                            temperature_found_count += 1
                            node_temperatures.setdefault(node_id, []).append(temp)
                except Exception as e:
                    decode_fail_count += 1
                    logger.debug(f"Failed to decode telemetry for node {node_id}: {e}")
                    continue

            logger.info(
                f"Temperature rankings: Decoded {decode_success_count}/{len(rows)} packets, "
                f"found {temperature_found_count} with temperature data, "
                f"{decode_fail_count} decode failures, "
                f"{len(node_temperatures)} nodes with temperature"
            )

            node_avg_temps: list[tuple[int, float]] = []
            for node_id, temps in node_temperatures.items():
                if temps:
                    avg_temp = sum(temps) / len(temps)
                    node_avg_temps.append((node_id, avg_temp))

            node_avg_temps.sort(key=lambda x: x[1], reverse=(order == "DESC"))

            for node_id, avg_temp in node_avg_temps[:limit]:
                info = node_info.get(node_id, {})
                display_name = info.get("long_name") or info.get("short_name")
                if not display_name and node_id is not None:
                    display_name = f"!{node_id:08x}"

                ranked_nodes.append(
                    {
                        "node_id": node_id,
                        "display_name": display_name,
                        "temperature": round(avg_temp, 1),
                        "temperature_count": len(node_temperatures[node_id]),
                        "hw_model": info.get("hw_model"),
                    }
                )

        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return ranked_nodes

    @staticmethod
    def _get_node_telemetry_rankings(
        filters: dict,
        since_timestamp: float,
        metric_type: str,
        order: str = "DESC",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get ranked nodes by telemetry metric (battery, humidity, voltage).

        Preference order:
        1. Use node_telemetry_latest if it has any recent rows for the metric.
        2. Fallback to decoding TELEMETRY_APP packets from packet_history.
        """
        from ..database.connection import get_db_connection, put_db_connection

        conn = None
        cursor = None
        ranked_nodes: list[dict[str, Any]] = []

        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Map metric_type to column in node_telemetry_latest
            metric_column_map = {
                "battery": "battery_level",
                "humidity": "humidity",
                "voltage": "voltage",
            }
            column = metric_column_map.get(metric_type)

            if column:
                where_clauses: list[str] = [
                    "ntl.last_updated >= to_timestamp(%s)",
                    f"ntl.{column} IS NOT NULL",
                ]
                params: list[Any] = [since_timestamp]

                if filters.get("gateway_id"):
                    where_clauses.append(
                        "EXISTS (SELECT 1 FROM packet_history ph "
                        "WHERE ph.from_node_id = ntl.node_id "
                        "AND ph.gateway_id = %s "
                        "AND ph.timestamp >= %s)"
                    )
                    params.extend([filters["gateway_id"], since_timestamp])

                where_sql = " AND ".join(where_clauses)

                cursor.execute(
                    f"""
                    SELECT
                        ntl.node_id,
                        ntl.{column} AS metric_value,
                        ntl.last_updated,
                        ni.long_name,
                        ni.short_name,
                        ni.hw_model
                    FROM node_telemetry_latest ntl
                    LEFT JOIN node_info ni ON ntl.node_id = ni.node_id
                    WHERE {where_sql}
                    ORDER BY ntl.{column} {"DESC" if order == "DESC" else "ASC"}
                    LIMIT %s
                    """,
                    (*params, limit),
                )
                rows = cursor.fetchall() or []

                if rows:
                    for row in rows:
                        node_id = row.get("node_id")
                        if node_id is None:
                            continue
                        display_name = row.get("long_name") or row.get("short_name")
                        if not display_name:
                            display_name = f"!{node_id:08x}"

                        value = row.get("metric_value")
                        if value is None:
                            continue

                        rounded = (
                            round(float(value), 2)
                            if metric_type == "voltage"
                            else round(float(value), 1)
                        )

                        ranked_nodes.append(
                            {
                                "node_id": node_id,
                                "display_name": display_name,
                                "metric_value": rounded,
                                "metric_count": 1,
                                "hw_model": row.get("hw_model"),
                            }
                        )

                    return ranked_nodes

            # Fallback: decode telemetry from packet_history
            try:
                from meshtastic import telemetry_pb2
            except ImportError:
                logger.warning(
                    "meshtastic protobuf not available, cannot decode telemetry"
                )
                return []

            where_conditions: list[str] = [
                "ph.timestamp >= %s",
                "ph.from_node_id IS NOT NULL",
                "ph.portnum_name = 'TELEMETRY_APP'",
                "ph.raw_payload IS NOT NULL",
            ]
            params = [since_timestamp]

            if filters.get("gateway_id"):
                where_conditions.append("ph.gateway_id = %s")
                params.append(filters["gateway_id"])

            where_clause = " AND ".join(where_conditions)

            query = f"""
                SELECT
                    ph.from_node_id AS node_id,
                    ph.raw_payload,
                    ph.timestamp,
                    ni.long_name,
                    ni.short_name,
                    ni.hw_model
                FROM packet_history ph
                LEFT JOIN node_info ni ON ph.from_node_id = ni.node_id
                WHERE {where_clause}
                ORDER BY ph.timestamp DESC
            """

            cursor.execute(query, params)
            rows = cursor.fetchall() or []

            node_metrics: dict[int, list[float]] = {}
            node_info: dict[int, dict[str, Any]] = {}

            for row in rows:
                node_id = row.get("node_id")
                if not node_id:
                    continue

                if node_id not in node_info:
                    node_info[node_id] = {
                        "long_name": row.get("long_name"),
                        "short_name": row.get("short_name"),
                        "hw_model": row.get("hw_model"),
                    }

                raw_payload = row.get("raw_payload")
                if not raw_payload:
                    continue

                try:
                    telemetry = telemetry_pb2.Telemetry()
                    if isinstance(raw_payload, bytes):
                        telemetry.ParseFromString(raw_payload)
                    elif isinstance(raw_payload, memoryview):
                        telemetry.ParseFromString(bytes(raw_payload))
                    else:
                        continue

                    metric_value = None
                    if metric_type == "battery" and telemetry.HasField(
                        "device_metrics"
                    ):
                        device_metrics = telemetry.device_metrics
                        if device_metrics.HasField("battery_level"):
                            metric_value = device_metrics.battery_level
                    elif metric_type == "voltage" and telemetry.HasField(
                        "device_metrics"
                    ):
                        device_metrics = telemetry.device_metrics
                        if device_metrics.HasField("voltage"):
                            metric_value = device_metrics.voltage / 1000.0
                    elif metric_type == "humidity" and telemetry.HasField(
                        "environment_metrics"
                    ):
                        env_metrics = telemetry.environment_metrics
                        if env_metrics.HasField("relative_humidity"):
                            metric_value = env_metrics.relative_humidity

                    if metric_value is not None:
                        node_metrics.setdefault(node_id, []).append(float(metric_value))
                except Exception as e:
                    logger.warning(
                        f"Failed to decode telemetry for node {node_id} (type={metric_type}): {e}"
                    )
                    continue

            node_avg_metrics: list[tuple[int, float]] = []

            for node_id, values in node_metrics.items():
                if values:
                    avg_value = sum(values) / len(values)
                    node_avg_metrics.append((node_id, avg_value))

            node_avg_metrics.sort(key=lambda x: x[1], reverse=(order == "DESC"))

            for node_id, avg_value in node_avg_metrics[:limit]:
                info = node_info.get(node_id, {})
                display_name = info.get("long_name") or info.get("short_name")
                if not display_name and node_id is not None:
                    display_name = f"!{node_id:08x}"

                ranked_nodes.append(
                    {
                        "node_id": node_id,
                        "display_name": display_name,
                        "metric_value": round(avg_value, 2)
                        if metric_type == "voltage"
                        else round(avg_value, 1),
                        "metric_count": len(node_metrics[node_id]),
                        "hw_model": info.get("hw_model"),
                    }
                )

        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return ranked_nodes

    @staticmethod
    def _get_channel_utilization(
        filters: dict, since_timestamp: float
    ) -> dict[str, Any]:
        """Get channel utilization metrics (bytes/packets per hour)."""
        from ..database.connection import get_db_connection, put_db_connection

        where_conditions: list[str] = ["timestamp >= %s"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = %s")
            params.append(filters["gateway_id"])

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                to_char(to_timestamp(timestamp), 'HH24') AS hour,
                COUNT(*) AS packet_count,
                SUM(COALESCE(payload_length, 0)) AS total_bytes
            FROM packet_history
            WHERE {where_clause}
            GROUP BY hour
            ORDER BY hour
        """

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            rows = cursor.fetchall()
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        utilization_data = []
        for row in rows:
            utilization_data.append(
                {
                    "hour": int(row["hour"]),
                    "packet_count": row["packet_count"],
                    "total_bytes": row["total_bytes"] or 0,
                }
            )

        return {"hourly_utilization": utilization_data}

    @staticmethod
    def _get_packet_type_distribution(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get distribution of packet types using optimized SQL query."""
        from ..database.connection import get_db_connection, put_db_connection

        # Build WHERE clause
        where_conditions: list[str] = ["timestamp >= %s", "portnum_name IS NOT NULL"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = %s")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = %s")
            params.append(filters["from_node"])

        where_clause = " AND ".join(where_conditions)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get packet type distribution with percentages
            cursor.execute(
                f"""
                WITH type_counts AS (
                    SELECT
                        portnum_name,
                        COUNT(*) as count
                    FROM packet_history
                    WHERE {where_clause}
                    GROUP BY portnum_name
                ),
                total_count AS (
                    SELECT SUM(count) as total FROM type_counts
                )
                SELECT
                    tc.portnum_name,
                    tc.count,
                    ROUND(tc.count * 100.0 / t.total, 2) as percentage
                FROM type_counts tc, total_count t
                ORDER BY tc.count DESC
                LIMIT 15
            """,
                params,
            )

            packet_types = [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return packet_types

    @staticmethod
    def _get_gateway_distribution(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get distribution of packets by gateway using optimized SQL query."""
        from ..database.connection import get_db_connection, put_db_connection

        # Build WHERE clause (excluding gateway_id filter since we're analyzing gateways)
        where_conditions: list[str] = ["timestamp >= %s"]
        params: list[Any] = [since_timestamp]

        if filters.get("from_node"):
            where_conditions.append("from_node_id = %s")
            params.append(filters["from_node"])

        where_clause = " AND ".join(where_conditions)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get gateway distribution with success rates and percentages
            cursor.execute(
                f"""
                WITH gateway_stats AS (
                    SELECT
                        COALESCE(gateway_id, 'Unknown') as gateway_id,
                        COUNT(*) as total_packets,
                        SUM(CASE WHEN processed_successfully THEN 1 ELSE 0 END) as successful_packets
                    FROM packet_history
                    WHERE {where_clause}
                    GROUP BY gateway_id
                ),
                total_count AS (
                    SELECT SUM(total_packets) as total FROM gateway_stats
                )
                SELECT
                    gs.gateway_id,
                    gs.total_packets,
                    gs.successful_packets,
                    ROUND(gs.successful_packets * 100.0 / gs.total_packets, 2) as success_rate,
                    ROUND(gs.total_packets * 100.0 / t.total, 2) as percentage_of_total
                FROM gateway_stats gs, total_count t
                ORDER BY gs.total_packets DESC
                LIMIT 20
            """,
                params,
            )

            gateway_stats = [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return gateway_stats
