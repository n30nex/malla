"""
Database connection management for Meshtastic Mesh Health Web UI.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from psycopg2 import OperationalError, pool
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from malla.config import get_config
from malla.exceptions import DatabaseConnectionError, DatabaseError

logger = logging.getLogger(__name__)

# Connection pool for PostgreSQL
_connection_pool: ThreadedConnectionPool | None = None
_migration_lock = threading.Lock()
_migrations_initialized = False


def get_db_connection() -> Any:
    """
    Get a connection to the configured PostgreSQL database.

    SQLite backends are intentionally disallowed (the project is PostgreSQL-only).
    """
    global _connection_pool

    config = get_config()

    if config.database_url and config.database_url.startswith("sqlite"):
        raise DatabaseConnectionError(
            "SQLite backend is not supported. Configure PostgreSQL via MALLA_DATABASE_URL "
            "or MALLA_DATABASE_HOST/PORT/NAME/USER/PASSWORD."
        )
    if config.database_file and (config.database_file != "meshtastic_history.db"):
        raise DatabaseConnectionError(
            "SQLite backend is not supported. Remove database_file or set PostgreSQL settings."
        )

    # Build connection parameters for PostgreSQL
    if config.database_url:
        conn_params = config.database_url
    else:
        conn_params = {
            "host": config.database_host or "localhost",
            "port": config.database_port or 5432,
            "database": config.database_name or "meshtastic_history",
            "user": config.database_user or os.getenv("USER", "postgres"),
            "password": config.database_password or "",
        }

    # Retry logic for database connections
    max_retries = int(os.getenv("MALLA_DB_CONNECT_RETRIES", "3"))
    retry_delay = float(os.getenv("MALLA_DB_CONNECT_RETRY_DELAY", "1.0"))

    for attempt in range(max_retries):
        try:
            # Initialize connection pool if not already done
            if _connection_pool is None:
                minconn = int(os.getenv("MALLA_DB_POOL_MIN", "1"))
                maxconn = int(os.getenv("MALLA_DB_POOL_MAX", "50"))
                maxconn = max(maxconn, minconn + 1)

                if isinstance(conn_params, str):
                    _connection_pool = ThreadedConnectionPool(
                        minconn=minconn, maxconn=maxconn, dsn=conn_params
                    )
                else:
                    _connection_pool = ThreadedConnectionPool(
                        minconn=minconn, maxconn=maxconn, **conn_params
                    )

            conn = _connection_pool.getconn()
            conn.autocommit = False

            _run_schema_migrations_once(conn)

            return conn
        except (OperationalError, pool.PoolError) as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Database connection attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts: {e}")
                raise DatabaseConnectionError(f"Failed to connect to database: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error connecting to database: {e}")
            raise DatabaseError(f"Database error: {e}") from e


def put_db_connection(conn: Any) -> None:
    """Return a connection to the pool."""
    global _connection_pool
    if conn is None:
        return

    if _connection_pool:
        try:
            try:
                # Ensure no open transaction is left behind
                conn.rollback()
            except Exception:
                pass
            _connection_pool.putconn(conn)
        except Exception as e:
            logger.warning(f"Error returning connection to pool: {e}")
            try:
                conn.close()
            except Exception:
                pass


def init_database() -> None:
    """Initialize the database connection and verify it's accessible."""
    config = get_config()

    if config.database_url:
        db_info = "connection string"
    else:
        db_info = f"{config.database_host or 'localhost'}:{config.database_port or 5432}/{config.database_name or 'meshtastic_history'}"

    logger.info(f"Initializing database connection to: {db_info}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
        result = cursor.fetchone()
        table_count = result["table_count"] if result else 0

        cursor.close()
        put_db_connection(conn)

        logger.info(f"Database connection successful - found {table_count} tables")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Do not raise so the app can still start if DB comes up later


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------

_SCHEMA_MIGRATIONS_DONE: set[str] = set()


def _ensure_tables(cursor: Any) -> None:
    """Ensure required tables exist."""
    # Table for packet history
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS packet_history (
            id BIGSERIAL PRIMARY KEY,
            timestamp DOUBLE PRECISION NOT NULL,
            topic TEXT NOT NULL,
            from_node_id BIGINT,
            to_node_id BIGINT,
            portnum INTEGER,
            portnum_name TEXT,
            gateway_id TEXT,
            channel_id TEXT,
            mesh_packet_id BIGINT,
            rssi INTEGER,
            snr DOUBLE PRECISION,
            hop_limit INTEGER,
            hop_start INTEGER,
            payload_length INTEGER,
            raw_payload BYTEA,
            processed_successfully BOOLEAN DEFAULT TRUE,
            via_mqtt BOOLEAN,
            want_ack BOOLEAN,
            priority INTEGER,
            delayed INTEGER,
            channel_index INTEGER,
            rx_time INTEGER,
            pki_encrypted BOOLEAN,
            next_hop BIGINT,
            relay_node BIGINT,
            tx_after INTEGER,
            message_type TEXT,
            raw_service_envelope BYTEA,
            parsing_error TEXT
        )
        """
    )

    # Table for node information cache
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS node_info (
            node_id BIGINT PRIMARY KEY,
            hex_id TEXT,
            long_name TEXT,
            short_name TEXT,
            hw_model TEXT,
            role TEXT,
            primary_channel TEXT,
            is_licensed BOOLEAN,
            mac_address TEXT,
            first_seen DOUBLE PRECISION NOT NULL,
            last_updated DOUBLE PRECISION NOT NULL
        )
        """
    )


def _ensure_schema_migrations(cursor: Any) -> None:
    """Run idempotent schema updates that the application depends on."""

    # Ensure base tables exist first
    _ensure_tables(cursor)

    migrations: dict[str, Any] = {
        "primary_channel": _migration_primary_channel,
        "bigint_node_ids": _migration_bigint_ids,
        "packet_indexes": _migration_packet_indexes,
    }

    for name, func in migrations.items():
        if name in _SCHEMA_MIGRATIONS_DONE:
            continue
        try:
            func(cursor)
            _SCHEMA_MIGRATIONS_DONE.add(name)
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc).lower()
            if "duplicate column" in error_msg or "already exists" in error_msg:
                _SCHEMA_MIGRATIONS_DONE.add(name)
            elif "cannot cast" in error_msg:
                logger.warning(
                    "Migration %s skipped due to cast issue (likely empty/new DB): %s",
                    name,
                    exc,
                )
                _SCHEMA_MIGRATIONS_DONE.add(name)
            else:
                raise


def _run_schema_migrations_once(conn: Any) -> None:
    """Run schema migrations only once per process to keep connection acquisition lightweight."""

    global _migrations_initialized
    if _migrations_initialized:
        return

    with _migration_lock:
        if _migrations_initialized:
            return

        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            _ensure_schema_migrations(cursor)
            conn.commit()
            _migrations_initialized = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Schema migration check failed: {exc}")
            conn.rollback()
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass


def _migration_primary_channel(cursor: Any) -> None:
    """Ensure primary_channel column exists on node_info."""
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'node_info' AND column_name = 'primary_channel'
        """
    )
    column_exists = cursor.fetchone() is not None

    if not column_exists:
        cursor.execute("ALTER TABLE node_info ADD COLUMN primary_channel TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_node_primary_channel ON node_info(primary_channel)"
        )
        logger.info(
            "Added primary_channel column to node_info table via auto-migration"
        )


def _migration_bigint_ids(cursor: Any) -> None:
    """Ensure node id columns are BIGINT to avoid overflow."""
    alter_statements = [
        "ALTER TABLE node_info ALTER COLUMN node_id TYPE BIGINT",
        "ALTER TABLE packet_history ALTER COLUMN from_node_id TYPE BIGINT",
        "ALTER TABLE packet_history ALTER COLUMN to_node_id TYPE BIGINT",
        "ALTER TABLE packet_history ALTER COLUMN mesh_packet_id TYPE BIGINT",
        "ALTER TABLE packet_history ALTER COLUMN next_hop TYPE BIGINT",
        "ALTER TABLE packet_history ALTER COLUMN relay_node TYPE BIGINT",
    ]

    for stmt in alter_statements:
        try:
            cursor.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "does not exist" in msg or "cannot alter type" in msg:
                continue
            if "integer out of range" in msg:
                continue
            raise


def _migration_packet_indexes(cursor: Any) -> None:
    """Create helpful indexes used by packet filters."""
    # Composite indexes for /api/nodes aggregation queries
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_packet_history_stats ON packet_history(timestamp, from_node_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_stats ON packet_history(timestamp, gateway_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_portnum_time ON packet_history(timestamp, portnum_name)",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_channel ON packet_history(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_to_node ON packet_history(to_node_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_id ON packet_history(gateway_id)",
        """CREATE INDEX IF NOT EXISTS idx_packet_history_direct_hops
           ON packet_history(timestamp, from_node_id, gateway_id, hop_start, hop_limit)
           WHERE hop_start = hop_limit""",
        """CREATE INDEX IF NOT EXISTS idx_packet_history_relay_time
           ON packet_history(timestamp, relay_node)
           WHERE relay_node IS NOT NULL AND relay_node != 0""",
        "CREATE INDEX IF NOT EXISTS idx_packet_mesh_id ON packet_history(mesh_packet_id)",
        "CREATE INDEX IF NOT EXISTS idx_node_hex_id ON node_info(hex_id)",
        # Legacy/Duplicate indexes (kept for compatibility or if names differ)
        "CREATE INDEX IF NOT EXISTS idx_packet_channel_id ON packet_history(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_gateway_id ON packet_history(gateway_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_to_node ON packet_history(to_node_id)",
        "CREATE INDEX IF NOT EXISTS idx_packet_portnum_name ON packet_history(portnum_name)",
    ]

    for stmt in index_statements:
        try:
            cursor.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate" in msg:
                continue
            # Handle deadlocks gracefully
            if "deadlock detected" in msg:
                logger.warning(
                    f"Skipped index creation due to deadlock: {stmt[:50]}..."
                )
                continue
            raise
