"""
Integration tests for data cleanup functionality.

Tests the automatic cleanup of old packet_history and node_info records
based on the data_retention_hours configuration parameter.
"""

import time

import pytest

from malla import mqtt_capture
from malla.database.connection import get_db_connection, put_db_connection
from psycopg2.extras import RealDictCursor


def _cleanup_test_data(node_ids: list[int]) -> None:
    """Remove any test data inserted by these tests."""
    if not node_ids:
        return

    with mqtt_capture.db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute("DELETE FROM packet_history WHERE topic LIKE 'test/%'")
            # Use IN clause with proper tuple formatting for PostgreSQL
            placeholders = ','.join(['%s'] * len(node_ids))
            cursor.execute(
                f"DELETE FROM node_info WHERE node_id IN ({placeholders})",
                tuple(node_ids),
            )
            conn.commit()
        finally:
            cursor.close()
            put_db_connection(conn)


class TestDataCleanup:
    """Test data cleanup functionality."""

    @pytest.mark.integration
    def test_cleanup_functionality(self):
        """Test that data cleanup correctly removes old records."""
        # Initialize the database
        mqtt_capture.init_database()

        # Use unique node IDs based on current time to avoid conflicts
        base_id = int(time.time() * 1000) % 0x7FFFFFFF  # Use timestamp-based unique IDs
        node_id_1 = base_id + 1
        node_id_2 = base_id + 2
        node_id_3 = base_id + 3
        node_ids = [node_id_1, node_id_2, node_id_3]

        # Get timestamps
        current_time = time.time()
        old_time = current_time - (48 * 3600)  # 48 hours ago
        cutoff_time = current_time - (24 * 3600)  # 24 hours ago (for cleanup verification)

        # Clean up any existing test data from previous runs first
        _cleanup_test_data(node_ids)
        # Also clean all test packets to avoid conflicts from parallel runs
        with mqtt_capture.db_lock:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cursor.execute("DELETE FROM packet_history WHERE topic LIKE 'test/%'")
                conn.commit()
            finally:
                cursor.close()
                put_db_connection(conn)

        # Insert test data
        with mqtt_capture.db_lock:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            try:
                # Insert old packet history records
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (%s, %s, %s, %s, %s, %s)",
                    (old_time, "test/topic", node_id_1, 654321, 1, "TEXT_MESSAGE_APP"),
                )
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        old_time + 3600,
                        "test/topic2",
                        node_id_2,
                        654322,
                        1,
                        "TEXT_MESSAGE_APP",
                    ),
                )

                # Insert recent packet history records
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        current_time - 3600,
                        "test/topic3",
                        node_id_3,
                        654323,
                        1,
                        "TEXT_MESSAGE_APP",
                    ),
                )

                # Insert old node info records (use ON CONFLICT to handle duplicates)
                cursor.execute(
                    """INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (node_id) DO UPDATE SET last_updated = EXCLUDED.last_updated""",
                    (node_id_1, f"!{node_id_1:08x}", "Old Node 1", "ON1", old_time, old_time),
                )
                cursor.execute(
                    """INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (node_id) DO UPDATE SET last_updated = EXCLUDED.last_updated""",
                    (node_id_2, f"!{node_id_2:08x}", "Old Node 2", "ON2", old_time, old_time),
                )

                # Insert recent node info records
                cursor.execute(
                    """INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (node_id) DO UPDATE SET last_updated = EXCLUDED.last_updated""",
                    (
                        node_id_3,
                        f"!{node_id_3:08x}",
                        "Recent Node",
                        "RN",
                        current_time - 3600,
                        current_time - 3600,
                    ),
                )

                conn.commit()
            finally:
                cursor.close()
                put_db_connection(conn)

        # Verify initial data - count only our test packets
        with mqtt_capture.db_lock:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            try:
                # Count only test packets (by topic prefix)
                cursor.execute("SELECT COUNT(*) as count FROM packet_history WHERE topic LIKE 'test/%'")
                test_packets = cursor.fetchone()["count"]

                # Count only test nodes (by our node IDs)
                cursor.execute(
                    "SELECT COUNT(*) as count FROM node_info WHERE node_id IN (%s, %s, %s)",
                    (node_id_1, node_id_2, node_id_3),
                )
                test_nodes = cursor.fetchone()["count"]

                assert test_packets == 3, f"Expected 3 test packets, got {test_packets}"
                assert test_nodes == 3, f"Expected 3 test nodes, got {test_nodes}"
            finally:
                cursor.close()
                put_db_connection(conn)

        # Override data retention hours to 24 hours
        original_retention = mqtt_capture.DATA_RETENTION_HOURS
        mqtt_capture.DATA_RETENTION_HOURS = 24

        try:
            # Run the cleanup function (ensure lock is released before calling)
            # Add a small delay to ensure any pending transactions are committed
            time.sleep(0.1)
            mqtt_capture.cleanup_old_data()

            # Verify cleanup results - check only our test data
            with mqtt_capture.db_lock:
                conn = get_db_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)

                try:
                    # Count remaining test packets
                    cursor.execute("SELECT COUNT(*) as count FROM packet_history WHERE topic LIKE 'test/%'")
                    remaining_test_packets = cursor.fetchone()["count"]

                    # Count remaining test nodes
                    cursor.execute(
                        "SELECT COUNT(*) as count FROM node_info WHERE node_id IN (%s, %s, %s)",
                        (node_id_1, node_id_2, node_id_3),
                    )
                    remaining_test_nodes = cursor.fetchone()["count"]

                    # Check that old test packets were deleted but recent ones remain
                    cursor.execute(
                        "SELECT COUNT(*) as count FROM packet_history WHERE topic LIKE 'test/%' AND timestamp < %s",
                        (cutoff_time,),
                    )
                    old_test_packets_remaining = cursor.fetchone()["count"]

                    # Check that old test nodes were deleted but recent ones remain
                    cursor.execute(
                        "SELECT COUNT(*) as count FROM node_info WHERE node_id IN (%s, %s, %s) AND last_updated < %s",
                        (node_id_1, node_id_2, node_id_3, cutoff_time),
                    )
                    old_test_nodes_remaining = cursor.fetchone()["count"]

                    # Verify results
                    assert remaining_test_packets == 1, (
                        f"Expected 1 test packet to remain, got {remaining_test_packets}"
                    )
                    assert remaining_test_nodes == 1, (
                        f"Expected 1 test node to remain, got {remaining_test_nodes}"
                    )
                    assert old_test_packets_remaining == 0, (
                        f"Expected 0 old test packets to remain, got {old_test_packets_remaining}"
                    )
                    assert old_test_nodes_remaining == 0, (
                        f"Expected 0 old test nodes to remain, got {old_test_nodes_remaining}"
                    )
                finally:
                    cursor.close()
                    put_db_connection(conn)

        finally:
            # Restore original retention hours and clean up inserted data
            mqtt_capture.DATA_RETENTION_HOURS = original_retention
            _cleanup_test_data(node_ids)

    @pytest.mark.integration
    def test_cleanup_disabled(self):
        """Test that cleanup is disabled when retention hours is 0."""
        # Initialize the database
        mqtt_capture.init_database()

        # Use unique node ID based on current time to avoid conflicts
        base_id = int(time.time() * 1000) % 0x7FFFFFFF
        node_id = base_id + 100
        node_ids = [node_id]

        # Clean up any existing test data from previous runs first
        _cleanup_test_data(node_ids)
        # Also clean all test packets to avoid conflicts from parallel runs
        with mqtt_capture.db_lock:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cursor.execute("DELETE FROM packet_history WHERE topic LIKE 'test/%'")
                conn.commit()
            finally:
                cursor.close()
                put_db_connection(conn)

        # Insert test data
        current_time = time.time()
        old_time = current_time - (48 * 3600)  # 48 hours ago

        with mqtt_capture.db_lock:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            try:
                # Insert old packet history records
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (%s, %s, %s, %s, %s, %s)",
                    (old_time, "test/topic", node_id, 654321, 1, "TEXT_MESSAGE_APP"),
                )

                # Insert old node info records (use ON CONFLICT to handle duplicates)
                cursor.execute(
                    """INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (node_id) DO UPDATE SET last_updated = EXCLUDED.last_updated""",
                    (node_id, f"!{node_id:08x}", "Old Node 1", "ON1", old_time, old_time),
                )

                conn.commit()
            finally:
                cursor.close()
                put_db_connection(conn)

        # Verify initial data - count only test packets
        with mqtt_capture.db_lock:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            try:
                cursor.execute("SELECT COUNT(*) as count FROM packet_history WHERE topic LIKE 'test/%'")
                initial_test_packets = cursor.fetchone()["count"]

                # Use IN clause with proper formatting
                placeholders = ','.join(['%s'] * len(node_ids))
                cursor.execute(
                    f"SELECT COUNT(*) as count FROM node_info WHERE node_id IN ({placeholders})",
                    tuple(node_ids),
                )
                initial_test_nodes = cursor.fetchone()["count"]

                assert initial_test_packets == 1, f"Expected 1 test packet initially, got {initial_test_packets}"
                assert initial_test_nodes == 1, f"Expected 1 test node initially, got {initial_test_nodes}"
            finally:
                cursor.close()
                put_db_connection(conn)

        # Override data retention hours to 0 (disabled)
        original_retention = mqtt_capture.DATA_RETENTION_HOURS
        mqtt_capture.DATA_RETENTION_HOURS = 0

        try:
            # Run the cleanup function
            mqtt_capture.cleanup_old_data()

            # Verify no cleanup occurred - check only test data
            with mqtt_capture.db_lock:
                conn = get_db_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)

                try:
                    cursor.execute("SELECT COUNT(*) as count FROM packet_history WHERE topic LIKE 'test/%'")
                    remaining_test_packets = cursor.fetchone()["count"]

                    # Use IN clause with proper formatting
                    placeholders = ','.join(['%s'] * len(node_ids))
                    cursor.execute(
                        f"SELECT COUNT(*) as count FROM node_info WHERE node_id IN ({placeholders})",
                        tuple(node_ids),
                    )
                    remaining_test_nodes = cursor.fetchone()["count"]

                    # Verify results - test data should remain unchanged
                    assert remaining_test_packets == initial_test_packets, (
                        f"Expected {initial_test_packets} test packets to remain, got {remaining_test_packets}"
                    )
                    assert remaining_test_nodes == initial_test_nodes, (
                        f"Expected {initial_test_nodes} test nodes to remain, got {remaining_test_nodes}"
                    )
                finally:
                    cursor.close()
                    put_db_connection(conn)

        finally:
            # Restore original retention hours and clean up inserted data
            mqtt_capture.DATA_RETENTION_HOURS = original_retention
            _cleanup_test_data(node_ids)
