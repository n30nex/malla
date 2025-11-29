#!/usr/bin/env python3
"""
Meshtastic MQTT to PostgreSQL Capture Tool

This script connects to a Meshtastic MQTT broker and captures all mesh packets
to a PostgreSQL database for analysis and monitoring. It processes protobuf messages
and extracts node information, telemetry, position data, and text messages.

Features:
- Automatic packet capture and storage
- Node information caching
- Packet decryption support for multiple channels
- Automatic data cleanup based on retention settings

Usage:
    malla-capture

Configuration:
    All runtime settings are loaded from ``config.yaml`` (or the file specified
    via ``$MALLA_CONFIG_FILE``).  Keys can also be overridden with
    ``MALLA_*``-prefixed environment variables (e.g. ``MALLA_MQTT_PORT``) but
    the old unprefixed environment variables are no longer supported.

Data Cleanup:
    The tool supports automatic cleanup of old data based on the
    ``data_retention_hours`` configuration parameter. When set to a positive
    value, the tool will automatically delete packet_history records older than
    the specified number of hours, and node_info records for nodes that haven't
    been seen recently and have no packets in the packet_history table.
    The cleanup runs every hour. Set to 0 (default) to disable cleanup.
"""

import base64
import hashlib
import logging
import socket
import threading
import time
from typing import Any

from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram, start_http_server

import paho.mqtt.client as mqtt
import psycopg2
from psycopg2 import errors
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from meshtastic import (
    config_pb2,
    mesh_pb2,
    mqtt_pb2,
    portnums_pb2,
    telemetry_pb2,
)
try:
    from paho.mqtt.enums import CallbackAPIVersion
except Exception:
    try:
        from paho.mqtt.client import CallbackAPIVersion  # type: ignore
    except Exception:
        class CallbackAPIVersion:  # type: ignore
            V5 = 5
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Configuration (centralised via malla.config)
# ---------------------------------------------------------------------------
from malla.config import get_config, validate_config  # Import here to avoid circular import issues
from malla.database.connection import get_db_connection, put_db_connection
from malla.logging_utils import setup_logging
from malla.telemetry import setup_telemetry

# Load the singleton configuration once at module import time.  This ensures the
# capture tool honours the same YAML + optional environment override mechanism
# as the web-UI and the rest of the application stack.

_cfg = get_config()

# MQTT Broker details
MQTT_BROKER_ADDRESS: str = _cfg.mqtt_broker_address
MQTT_PORT: int = _cfg.mqtt_port
MQTT_USERNAME: str | None = _cfg.mqtt_username
MQTT_PASSWORD: str | None = _cfg.mqtt_password
MQTT_TOPIC_PREFIX: str = _cfg.mqtt_topic_prefix
MQTT_TOPIC_SUFFIX: str = _cfg.mqtt_topic_suffix
MQTT_KEEPALIVE: int = _cfg.mqtt_keepalive
MQTT_QOS: int = _cfg.mqtt_qos
MQTT_CLEAN_SESSION: bool = _cfg.mqtt_clean_session
MQTT_TLS_ENABLED: bool = _cfg.mqtt_tls_enabled
MQTT_TLS_CA_CERT: str | None = _cfg.mqtt_tls_ca_cert
MQTT_TLS_CLIENT_CERT: str | None = _cfg.mqtt_tls_client_cert
MQTT_TLS_CLIENT_KEY: str | None = _cfg.mqtt_tls_client_key
MQTT_TLS_INSECURE: bool = _cfg.mqtt_tls_insecure
MQTT_RECONNECT_MAX_RETRIES: int = max(1, _cfg.mqtt_reconnect_max_retries)
MQTT_RECONNECT_BASE_DELAY: int = max(1, _cfg.mqtt_reconnect_base_delay)
MQTT_RECONNECT_MAX_DELAY: int = max(MQTT_RECONNECT_BASE_DELAY, _cfg.mqtt_reconnect_max_delay)

# Database file path
DATABASE_FILE: str = _cfg.database_file

# Decryption keys for secondary channels (optional)
# Supports multiple comma-separated keys
DECRYPTION_KEYS: list[str] = _cfg.get_decryption_keys()

# Data retention settings
DATA_RETENTION_HOURS: int = _cfg.data_retention_hours
DATA_CLEANUP_INTERVAL_SECONDS: int = max(60, int(getattr(_cfg, "data_cleanup_interval_seconds", 3600)))
METRICS_ENABLED: bool = getattr(_cfg, "metrics_enabled", False)
METRICS_PORT: int = getattr(_cfg, "metrics_port", 9100)

# Logging configuration - falls back to INFO if an invalid level was supplied
LOG_LEVEL = _cfg.log_level.upper()
setup_logging(LOG_LEVEL)

# Validate config and enable OpenTelemetry if configured
validate_config(_cfg)

if _cfg.otlp_endpoint:
    try:
        setup_telemetry(None, _cfg.otlp_endpoint)
        logging.info("OpenTelemetry enabled for capture process")
    except Exception as exc:  # noqa: BLE001
        logging.warning(f"Failed to initialize OpenTelemetry: {exc}")

# --- Global Variables ---
db_lock = threading.Lock()  # Thread lock for database access
node_cache: dict[
    int, dict[str, Any]
] = {}  # In-memory cache: {node_id_numeric: {'hex_id': '!abc123', 'long_name': 'Name', 'short_name': 'Short', 'last_updated': timestamp}}
cleanup_thread: threading.Thread | None = None  # Background thread for data cleanup
stop_cleanup = threading.Event()  # Event to signal cleanup thread to stop
ingest_stats_lock = threading.Lock()
ingest_stats = {
    "received": 0,
    "parsed_ok": 0,
    "parse_failed": 0,
    "decrypt_success": 0,
    "decrypt_failed": 0,
}

# Prometheus metrics (counters accumulate; optional HTTP exporter)
# Use try/except to handle duplicate registration during module reloads
try:
    PACKETS_RECEIVED = Counter("malla_packets_received_total", "MQTT messages received")
except ValueError:
    from prometheus_client import REGISTRY
    PACKETS_RECEIVED = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_packets_received_total"), None)
    if PACKETS_RECEIVED is None:
        raise

try:
    PACKETS_PARSED = Counter("malla_packets_parsed_total", "Packets parsed successfully")
except ValueError:
    from prometheus_client import REGISTRY
    PACKETS_PARSED = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_packets_parsed_total"), None)
    if PACKETS_PARSED is None:
        raise

try:
    PACKETS_PARSE_FAILED = Counter("malla_packets_parse_failed_total", "Packets that failed to parse")
except ValueError:
    from prometheus_client import REGISTRY
    PACKETS_PARSE_FAILED = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_packets_parse_failed_total"), None)
    if PACKETS_PARSE_FAILED is None:
        raise

try:
    PACKETS_DECRYPT_SUCCESS = Counter("malla_packets_decrypt_success_total", "Packets decrypted successfully")
except ValueError:
    from prometheus_client import REGISTRY
    PACKETS_DECRYPT_SUCCESS = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_packets_decrypt_success_total"), None)
    if PACKETS_DECRYPT_SUCCESS is None:
        raise

try:
    PACKETS_DECRYPT_FAILED = Counter("malla_packets_decrypt_failed_total", "Packets failed to decrypt")
except ValueError:
    from prometheus_client import REGISTRY
    PACKETS_DECRYPT_FAILED = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_packets_decrypt_failed_total"), None)
    if PACKETS_DECRYPT_FAILED is None:
        raise

try:
    ACTIVE_THREADS = Gauge("malla_active_threads", "Active threads in capture process")
except ValueError:
    from prometheus_client import REGISTRY
    ACTIVE_THREADS = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_active_threads"), None)
    if ACTIVE_THREADS is None:
        raise

try:
    DB_QUERY_DURATION = Histogram(
        "malla_capture_db_query_seconds",
        "Database operation duration in seconds (capture service)",
        ["operation"],
    )
except ValueError:
    from prometheus_client import REGISTRY
    DB_QUERY_DURATION = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_capture_db_query_seconds"), None)
    if DB_QUERY_DURATION is None:
        raise

try:
    PACKET_PROCESS_DURATION = Histogram(
        "malla_packet_process_seconds",
        "End-to-end MQTT packet processing duration in seconds",
        ["stage"],
    )
except ValueError:
    from prometheus_client import REGISTRY
    PACKET_PROCESS_DURATION = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_packet_process_seconds"), None)
    if PACKET_PROCESS_DURATION is None:
        raise

try:
    CLEANUP_FAILURES = Counter(
        "malla_data_cleanup_failures_total",
        "Total number of data cleanup failures",
    )
except ValueError:
    from prometheus_client import REGISTRY
    CLEANUP_FAILURES = next((c for c in REGISTRY._collector_to_names.keys() if hasattr(c, '_name') and c._name == "malla_data_cleanup_failures_total"), None)
    if CLEANUP_FAILURES is None:
        raise

TRACER = trace.get_tracer(__name__)


# --- Decryption Functions ---
def derive_key_from_channel_name(channel_name: str, key_base64: str) -> bytes:
    """
    Derive encryption key from channel name and base key.
    This follows Meshtastic's key derivation algorithm.
    """
    try:
        # Decode the base key from base64
        key_bytes = base64.b64decode(key_base64)

        # If channel name is provided, derive key using SHA256
        if channel_name and channel_name != "":
            # Convert channel name to bytes
            channel_bytes = channel_name.encode("utf-8")
            # Create SHA256 hash of base key + channel name
            hasher = hashlib.sha256()
            hasher.update(key_bytes)
            hasher.update(channel_bytes)
            derived_key = hasher.digest()
            return derived_key
        else:
            # For primary channel, use the key as-is (should already be 32 bytes for AES256)
            return key_bytes
    except Exception as e:
        logging.warning(f"Error deriving key: {e}")
        return b"\x00" * 32  # Return null key on error


def decrypt_packet(
    encrypted_payload: bytes, packet_id: int, sender_id: int, key: bytes
) -> bytes:
    """
    Decrypt a Meshtastic packet using AES256-CTR.

    Args:
        encrypted_payload: The encrypted payload bytes
        packet_id: The packet ID for nonce construction
        sender_id: The sender node ID for nonce construction
        key: The encryption key (32 bytes for AES256)

    Returns:
        Decrypted payload bytes or empty bytes if decryption fails
    """
    try:
        if len(encrypted_payload) == 0:
            logging.debug("Empty encrypted payload, nothing to decrypt")
            return b""

        # Construct nonce: packet_id (8 bytes) + sender_id (8 bytes) = 16 bytes
        packet_id_bytes = packet_id.to_bytes(8, byteorder="little")
        sender_id_bytes = sender_id.to_bytes(8, byteorder="little")
        nonce = packet_id_bytes + sender_id_bytes

        if len(nonce) != 16:
            logging.warning(f"Invalid nonce length: {len(nonce)}, expected 16 bytes")
            return b""

        # Create AES-CTR cipher
        cipher = Cipher(
            algorithms.AES(key), modes.CTR(nonce), backend=default_backend()
        )
        decryptor = cipher.decryptor()

        # Decrypt the payload
        decrypted = decryptor.update(encrypted_payload) + decryptor.finalize()

        logging.debug(
            f"Successfully decrypted {len(encrypted_payload)} bytes to {len(decrypted)} bytes"
        )
        return decrypted

    except Exception as e:
        logging.warning(f"Decryption failed: {e}")
        return b""


def try_decrypt_mesh_packet(
    mesh_packet: Any, channel_name: str = "", keys_base64: list[str] | None = None
) -> bool:
    """
    Try to decrypt an encrypted MeshPacket and update it with decoded content.

    Attempts decryption with each key in the provided list until successful.

    Args:
        mesh_packet: The MeshPacket protobuf object
        channel_name: Channel name for key derivation (empty for primary channel)
        keys_base64: List of base64-encoded encryption keys to try (uses DECRYPTION_KEYS if None)

    Returns:
        bool: True if decryption was successful and packet was updated
    """
    try:
        # Check if packet already has decoded data
        if (
            hasattr(mesh_packet, "decoded")
            and mesh_packet.decoded.portnum != portnums_pb2.PortNum.UNKNOWN_APP
        ):
            logging.debug("Packet already decoded successfully")
            return False

        # Check if packet has encrypted data
        if not hasattr(mesh_packet, "encrypted") or not mesh_packet.encrypted:
            logging.debug("No encrypted payload found in packet")
            return False

        encrypted_payload = mesh_packet.encrypted
        packet_id = mesh_packet.id
        sender_id = getattr(mesh_packet, "from")  # 'from' is a Python keyword

        logging.debug(
            f"Attempting to decrypt packet {packet_id} from {sender_id}, encrypted payload: {len(encrypted_payload)} bytes"
        )

        # Use provided keys or fall back to global DECRYPTION_KEYS
        keys_to_try = keys_base64 if keys_base64 is not None else DECRYPTION_KEYS

        if not keys_to_try:
            logging.debug("No decryption keys configured")
            return False

        # Try each key until one works
        for key_index, key_base64 in enumerate(keys_to_try):
            logging.debug(f"Trying decryption key {key_index + 1}/{len(keys_to_try)}")

            # Derive the decryption key
            key = derive_key_from_channel_name(channel_name, key_base64)

            # Decrypt the payload
            decrypted_payload = decrypt_packet(
                encrypted_payload, packet_id, sender_id, key
            )

            if not decrypted_payload:
                logging.debug(
                    f"Decryption with key {key_index + 1} returned empty payload"
                )
                continue

            # Try to parse the decrypted payload as a Data protobuf
            try:
                decoded_data = mesh_pb2.Data()
                decoded_data.ParseFromString(decrypted_payload)

                # Validate that we got a valid portnum (not UNKNOWN_APP)
                if decoded_data.portnum == portnums_pb2.PortNum.UNKNOWN_APP:
                    logging.debug(
                        f"Key {key_index + 1} produced UNKNOWN_APP portnum, trying next key"
                    )
                    continue

                # Update the mesh packet with decoded data
                mesh_packet.decoded.CopyFrom(decoded_data)

                logging.info(
                    f"Successfully decrypted packet {packet_id} from {sender_id} with key {key_index + 1}/{len(keys_to_try)}: {portnums_pb2.PortNum.Name(decoded_data.portnum)}"
                )
                return True

            except Exception as parse_error:
                logging.debug(
                    f"Failed to parse decrypted payload with key {key_index + 1} as Data protobuf: {parse_error}"
                )
                continue

        logging.debug(
            f"Failed to decrypt packet with any of the {len(keys_to_try)} provided keys"
        )
        return False

    except Exception as e:
        logging.warning(f"Error in try_decrypt_mesh_packet: {e}")
        return False


# --- Database Functions ---
def init_database() -> None:
    """Initialize PostgreSQL database with required tables."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Avoid startup deadlocks when multiple services initialize at once
    try:
        cursor.execute("SET lock_timeout TO '5s'")
    except Exception:
        logging.debug("Could not set lock_timeout; continuing without it")

    def _create_index(sql: str) -> None:
        """Create index with deadlock tolerance."""
        try:
            cursor.execute(sql)
            conn.commit()
        except errors.DeadlockDetected as exc:
            logging.warning(f"Skipped index creation due to deadlock: {exc}")
            conn.rollback()
        except Exception as exc:
            # Non-fatal: log and continue
            logging.warning(f"Index creation failed ({sql[:60]}...): {exc}")
            conn.rollback()

    try:
        # Table for packet history
        cursor.execute("""
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
                message_type TEXT,
                raw_service_envelope BYTEA,
                parsing_error TEXT
            )
        """)
        conn.commit()
    except Exception as e:
        logging.error(f"Error creating packet_history table: {e}")
        conn.rollback()
        raise

    # Add mesh_packet_id column if it doesn't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE packet_history ADD COLUMN mesh_packet_id BIGINT")
        logging.info("Added mesh_packet_id column to packet_history table")
        conn.commit()
    except Exception as e:
        error_msg = str(e).lower()
        if "duplicate column" in error_msg or "already exists" in error_msg:
            logging.debug("mesh_packet_id column already exists")
            conn.rollback()
        else:
            logging.warning(f"Could not add mesh_packet_id column: {e}")
            conn.rollback()

    # Add new MeshPacket fields if they don't exist (for existing databases)
    new_columns = [
        ("via_mqtt", "BOOLEAN"),
        ("want_ack", "BOOLEAN"),
        ("priority", "INTEGER"),
        ("delayed", "INTEGER"),
        ("channel_index", "INTEGER"),
        ("rx_time", "INTEGER"),
        ("pki_encrypted", "BOOLEAN"),
        ("next_hop", "BIGINT"),
        ("relay_node", "BIGINT"),
        ("tx_after", "INTEGER"),
        ("message_type", "TEXT"),
        ("raw_service_envelope", "BYTEA"),
        ("parsing_error", "TEXT"),
    ]

    for column_name, column_type in new_columns:
        try:
            cursor.execute(
                f"ALTER TABLE packet_history ADD COLUMN {column_name} {column_type}"
            )
            logging.info(f"Added {column_name} column to packet_history table")
            conn.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate column" in error_msg or "already exists" in error_msg:
                logging.debug(f"{column_name} column already exists")
                conn.rollback()
            else:
                logging.warning(f"Could not add {column_name} column: {e}")
                conn.rollback()

    try:
        # Table for node information cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_info (
                node_id INTEGER PRIMARY KEY,
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
        """)
        conn.commit()
    except Exception as e:
        logging.error(f"Error creating node_info table: {e}")
        conn.rollback()
        raise

    # Composite indexes for /api/nodes aggregation queries (96% faster than single-column indexes)
    # These covering indexes allow PostgreSQL to perform aggregations using only the index
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_history_stats ON packet_history(timestamp, from_node_id)"
    )
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_stats ON packet_history(timestamp, gateway_id)"
    )

    # Additional proven performance indexes (20-40% improvements, cache-aware benchmarked)
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_history_portnum_time ON packet_history(timestamp, portnum_name)"
    )
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_history_channel ON packet_history(channel_id)"
    )
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_history_to_node ON packet_history(to_node_id)"
    )
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_id ON packet_history(gateway_id)"
    )
    _create_index(
        """CREATE INDEX IF NOT EXISTS idx_packet_history_direct_hops
           ON packet_history(timestamp, from_node_id, gateway_id, hop_start, hop_limit)
           WHERE hop_start = hop_limit"""
    )
    _create_index(
        """CREATE INDEX IF NOT EXISTS idx_packet_history_relay_time
           ON packet_history(timestamp, relay_node)
           WHERE relay_node IS NOT NULL AND relay_node != 0"""
    )

    # Keep mesh_packet_id index (used for packet lookups)
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_packet_mesh_id ON packet_history(mesh_packet_id)"
    )

    # Drop old redundant indexes (composite indexes above can serve the same queries via leftmost prefix)
    try:
        cursor.execute("DROP INDEX IF EXISTS idx_packet_timestamp")
    except Exception:
        pass
    try:
        cursor.execute("DROP INDEX IF EXISTS idx_packet_from_node")
    except Exception:
        pass

    _create_index("CREATE INDEX IF NOT EXISTS idx_node_hex_id ON node_info(hex_id)")

    # Ensure primary_channel column exists for legacy databases
    try:
        cursor.execute("ALTER TABLE node_info ADD COLUMN primary_channel TEXT")
        logging.info("Added primary_channel column to node_info table")
        conn.commit()
    except Exception as e:
        error_msg = str(e).lower()
        if "duplicate column" in error_msg or "already exists" in error_msg:
            logging.debug("primary_channel column already exists")
            conn.rollback()
        else:
            logging.warning(f"Could not add primary_channel column: {e}")
            conn.rollback()

    # Index for faster channel filtering
    _create_index(
        "CREATE INDEX IF NOT EXISTS idx_node_primary_channel ON node_info(primary_channel)"
    )

    # Backfill primary_channel using last NODEINFO packets if missing
    try:
        cursor.execute(
            """
            UPDATE node_info
            SET primary_channel = (
                SELECT ph.channel_id
                FROM packet_history ph
                WHERE ph.from_node_id = node_info.node_id
                  AND ph.portnum_name = 'NODEINFO_APP'
                  AND ph.channel_id IS NOT NULL AND ph.channel_id != ''
                ORDER BY ph.timestamp DESC
                LIMIT 1
            )
            WHERE (primary_channel IS NULL OR primary_channel = '')
        """
        )
        logging.info("Backfilled primary_channel values in node_info table")
        conn.commit()
    except Exception as e:
        logging.warning(f"Could not backfill primary_channel column: {e}")
        conn.rollback()

    cursor.close()
    put_db_connection(conn)
    logging.info("Database initialized")


def load_node_cache() -> None:
    """Load node information from database into memory cache."""
    global node_cache
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT node_id, hex_id, long_name, short_name, hw_model, role,
                       is_licensed, mac_address, primary_channel, last_updated
                FROM node_info
                """
            )

            rows = cursor.fetchall()
            node_cache = {}

            for row in rows:
                node_id = row["node_id"]
                node_cache[node_id] = {
                    "hex_id": row["hex_id"],
                    "long_name": row["long_name"],
                    "short_name": row["short_name"],
                    "hw_model": row["hw_model"],
                    "role": row["role"],
                    "is_licensed": bool(row["is_licensed"])
                    if row["is_licensed"] is not None
                    else None,
                    "mac_address": row["mac_address"],
                    "primary_channel": row["primary_channel"],
                    "last_updated": row["last_updated"],
                }

            logging.info(f"Loaded {len(node_cache)} nodes into cache from database")
        finally:
            try:
                cursor.close()
            finally:
                put_db_connection(conn)


def update_node_cache(
    node_id: int,
    hex_id: str | None = None,
    long_name: str | None = None,
    short_name: str | None = None,
    hw_model: str | None = None,
    role: str | None = None,
    is_licensed: bool | None = None,
    mac_address: str | None = None,
    primary_channel: str | None = None,
) -> None:
    """Update both in-memory cache and database with node information."""
    global node_cache
    current_time = time.time()

    # Check if this is a new node (not in cache)
    is_new_node = node_id not in node_cache

    # Update in-memory cache
    if is_new_node:
        node_cache[node_id] = {
            "hex_id": hex_id,
            "long_name": long_name,
            "short_name": short_name,
            "hw_model": hw_model,
            "role": role,
            "is_licensed": is_licensed,
            "mac_address": mac_address,
            "primary_channel": primary_channel,
            "last_updated": current_time,
        }
    else:
        # Update existing entry with new non-None values
        if hex_id is not None:
            node_cache[node_id]["hex_id"] = hex_id
        if long_name is not None:
            node_cache[node_id]["long_name"] = long_name
        if short_name is not None:
            node_cache[node_id]["short_name"] = short_name
        if hw_model is not None:
            node_cache[node_id]["hw_model"] = hw_model
        if role is not None:
            node_cache[node_id]["role"] = role
        if is_licensed is not None:
            node_cache[node_id]["is_licensed"] = is_licensed
        if mac_address is not None:
            node_cache[node_id]["mac_address"] = mac_address
        if primary_channel is not None:
            node_cache[node_id]["primary_channel"] = primary_channel
        node_cache[node_id]["last_updated"] = current_time

    # Update database using INSERT ... ON CONFLICT to handle existing nodes
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get existing values from database if node exists
            cursor.execute(
                "SELECT hex_id, long_name, short_name, hw_model, role, is_licensed, mac_address, primary_channel, first_seen FROM node_info WHERE node_id = %s",
                (node_id,),
            )
            existing = cursor.fetchone()

            if existing:
                # Node exists, merge values (keep existing values if new values are None)
                final_hex_id = hex_id if hex_id is not None else existing["hex_id"]
                final_long_name = (
                    long_name if long_name is not None else existing["long_name"]
                )
                final_short_name = (
                    short_name if short_name is not None else existing["short_name"]
                )
                final_hw_model = hw_model if hw_model is not None else existing["hw_model"]
                final_role = role if role is not None else existing["role"]
                final_is_licensed = (
                    is_licensed if is_licensed is not None else existing["is_licensed"]
                )
                final_mac_address = (
                    mac_address if mac_address is not None else existing["mac_address"]
                )
                final_primary_channel = (
                    primary_channel
                    if primary_channel is not None
                    else existing["primary_channel"]
                )

                cursor.execute(
                    """
                    UPDATE node_info
                    SET hex_id = %s, long_name = %s, short_name = %s, hw_model = %s, role = %s,
                        is_licensed = %s, mac_address = %s, primary_channel = %s, last_updated = %s
                    WHERE node_id = %s
                """,
                    (
                        final_hex_id,
                        final_long_name,
                        final_short_name,
                        final_hw_model,
                        final_role,
                        final_is_licensed,
                        final_mac_address,
                        final_primary_channel,
                        current_time,
                        node_id,
                    ),
                )

                logging.debug(
                    f"Updated existing node in database: {node_id} ({final_hex_id})"
                )
            else:
                # New node, insert it
                cursor.execute(
                    """
                    INSERT INTO node_info
                    (node_id, hex_id, long_name, short_name, hw_model, role,
                     is_licensed, mac_address, primary_channel, first_seen, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        node_id,
                        hex_id,
                        long_name,
                        short_name,
                        hw_model,
                        role,
                        is_licensed,
                        mac_address,
                        primary_channel,
                        current_time,
                        current_time,
                    ),
                )

                logging.debug(f"Added new node to database: {node_id} ({hex_id})")

            conn.commit()
        finally:
            try:
                cursor.close()
            finally:
                put_db_connection(conn)


def hex_id_to_numeric(hex_id: str) -> int | None:
    """Convert hex node ID (like '!abcdef12') to numeric ID."""
    if not hex_id or not isinstance(hex_id, str):
        return None

    # Remove the '!' prefix if present
    if hex_id.startswith("!"):
        hex_id = hex_id[1:]

    try:
        # Convert hex string to integer
        return int(hex_id, 16)
    except ValueError:
        return None


def get_node_display_name(node_id: int | None) -> str:
    """Get the best display name for a node ID, using cache if available."""
    if node_id is None:
        return "Unknown"

    if node_id in node_cache:
        cache_entry = node_cache[node_id]
        long_name = cache_entry.get("long_name")
        short_name = cache_entry.get("short_name")
        hex_id = cache_entry.get("hex_id")

        if long_name:
            return f"{long_name} ({hex_id or f'Node {node_id:08x}'})"
        elif short_name:
            return f"{short_name} ({hex_id or f'Node {node_id:08x}'})"
        elif hex_id:
            return f"{hex_id} (Node {node_id:08x})"

    # No cache entry
    return f"Node {node_id:08x}"


def get_gateway_display_name(gateway_hex_id: str) -> str:
    """Get the best display name for a gateway hex ID, using cache if available."""
    if not gateway_hex_id:
        return "N/A"

    # Try to convert hex ID to numeric and look up in cache
    numeric_id = hex_id_to_numeric(gateway_hex_id)
    if numeric_id and numeric_id in node_cache:
        cache_entry = node_cache[numeric_id]
        long_name = cache_entry.get("long_name")
        short_name = cache_entry.get("short_name")

        if long_name:
            return f"{long_name} ({gateway_hex_id})"
        elif short_name:
            return f"{short_name} ({gateway_hex_id})"

    # Fall back to just the hex ID
    return gateway_hex_id


def log_packet_to_database(
    topic: str,
    service_envelope: Any | None,
    mesh_packet: Any | None,
    processed_successfully: bool = True,
    raw_service_envelope_data: bytes | None = None,
    parsing_error: str | None = None,
) -> None:
    """Log received packet to database for history tracking."""
    current_time = time.time()

    from_node_id = getattr(mesh_packet, "from", None) if mesh_packet else None
    to_node_id = getattr(mesh_packet, "to", None) if mesh_packet else None
    mesh_packet_id = getattr(mesh_packet, "id", None) if mesh_packet else None
    portnum = (
        mesh_packet.decoded.portnum
        if mesh_packet and hasattr(mesh_packet, "decoded")
        else None
    )
    portnum_name = portnums_pb2.PortNum.Name(portnum) if portnum is not None else None
    gateway_id = (
        getattr(service_envelope, "gateway_id", None) if service_envelope else None
    )
    channel_id = (
        getattr(service_envelope, "channel_id", None) if service_envelope else None
    )
    rssi = (
        getattr(mesh_packet, "rx_rssi", None)
        if mesh_packet and hasattr(mesh_packet, "rx_rssi")
        else None
    )
    snr = (
        getattr(mesh_packet, "rx_snr", None)
        if mesh_packet and hasattr(mesh_packet, "rx_snr")
        else None
    )
    hop_limit = getattr(mesh_packet, "hop_limit", None) if mesh_packet else None
    hop_start = getattr(mesh_packet, "hop_start", None) if mesh_packet else None
    payload_length = (
        len(mesh_packet.decoded.payload)
        if mesh_packet
        and hasattr(mesh_packet, "decoded")
        and hasattr(mesh_packet.decoded, "payload")
        else 0
    )
    raw_payload = (
        mesh_packet.decoded.payload
        if mesh_packet
        and hasattr(mesh_packet, "decoded")
        and hasattr(mesh_packet.decoded, "payload")
        else b""
    )

    # Extract message type from topic (e.g., 'e' for encrypted, 'c' for command, 'p' for position)
    message_type = None
    try:
        topic_parts = topic.split("/")
        if len(topic_parts) >= 4:
            message_type = topic_parts[3]  # Should be 'e', 'c', 'p', etc.
    except Exception:
        pass

    # Extract new MeshPacket fields
    via_mqtt = getattr(mesh_packet, "via_mqtt", None) if mesh_packet else None
    want_ack = getattr(mesh_packet, "want_ack", None) if mesh_packet else None
    priority = getattr(mesh_packet, "priority", None) if mesh_packet else None
    delayed = getattr(mesh_packet, "delayed", None) if mesh_packet else None
    channel_index = getattr(mesh_packet, "channel_index", None) if mesh_packet else None
    rx_time = getattr(mesh_packet, "rx_time", None) if mesh_packet else None
    pki_encrypted = getattr(mesh_packet, "pki_encrypted", None) if mesh_packet else None
    next_hop = getattr(mesh_packet, "next_hop", None) if mesh_packet else None
    relay_node = getattr(mesh_packet, "relay_node", None) if mesh_packet else None
    tx_after = getattr(mesh_packet, "tx_after", None) if mesh_packet else None

    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            with TRACER.start_as_current_span("db.insert.packet_history") as span, DB_QUERY_DURATION.labels(
                "insert_packet_history"
            ).time():
                if span is not None:
                    span.set_attribute("db.topic", topic)
                    span.set_attribute("db.gateway_id", gateway_id or "")
                    span.set_attribute("db.channel_id", channel_id or "")
                    span.set_attribute("db.portnum_name", portnum_name or "")
                    span.set_attribute("db.processed_successfully", processed_successfully)

                cursor.execute(
                    """
                    INSERT INTO packet_history
                    (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                     gateway_id, channel_id, mesh_packet_id, rssi, snr, hop_limit, hop_start, payload_length,
                     raw_payload, processed_successfully, via_mqtt, want_ack, priority, delayed,
                     channel_index, rx_time, pki_encrypted, next_hop, relay_node, tx_after,
                     message_type, raw_service_envelope, parsing_error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        current_time,
                        topic,
                        from_node_id,
                        to_node_id,
                        portnum,
                        portnum_name,
                        gateway_id,
                        channel_id,
                        mesh_packet_id,
                        rssi,
                        snr,
                        hop_limit,
                        hop_start,
                        payload_length,
                        raw_payload,
                        processed_successfully,
                        via_mqtt,
                        want_ack,
                        priority,
                        delayed,
                        channel_index,
                        rx_time,
                        pki_encrypted,
                        next_hop,
                        relay_node,
                        tx_after,
                        message_type,
                        raw_service_envelope_data,
                        parsing_error,
                    ),
                )

                conn.commit()
        finally:
            try:
                cursor.close()
            finally:
                put_db_connection(conn)


def get_packet_history(
    limit: int = 100, node_id: int | None = None, portnum: int | None = None
) -> list[dict[str, Any]]:
    """Get recent packet history from database."""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = "SELECT * FROM packet_history WHERE 1=1"
            params = []

            if node_id is not None:
                query += " AND from_node_id = %s"
                params.append(node_id)

            if portnum is not None:
                query += " AND portnum = %s"
                params.append(portnum)

            query += " ORDER BY timestamp DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            return rows
        finally:
            try:
                cursor.close()
            finally:
                put_db_connection(conn)


def cleanup_old_data() -> None:
    """Clean up old data from the database based on retention settings."""
    if DATA_RETENTION_HOURS <= 0:
        logging.debug("Data cleanup disabled (retention hours set to 0)")
        return

    logging.info(f"Data cleanup started for retention hours: {DATA_RETENTION_HOURS}")
    current_time = time.time()
    cutoff_time = current_time - (DATA_RETENTION_HOURS * 3600)

    packets_deleted = 0
    nodes_deleted = 0

    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Delete old packet history records in small batches to avoid long locks
            while True:
                cursor.execute(
                    """
                    DELETE FROM packet_history
                    WHERE ctid IN (
                        SELECT ctid FROM packet_history
                        WHERE timestamp < %s
                        ORDER BY timestamp ASC
                        LIMIT 5000
                    )
                    """,
                    (cutoff_time,),
                )
                batch_deleted = cursor.rowcount
                packets_deleted += batch_deleted
                conn.commit()
                if batch_deleted < 5000:
                    break

            # Delete node_info records for nodes that haven't been seen recently
            # and have no packets in the packet_history table
            while True:
                cursor.execute(
                    """
                    DELETE FROM node_info
                    WHERE ctid IN (
                        SELECT ctid FROM node_info
                        WHERE last_updated < %s
                        AND node_id NOT IN (
                            SELECT DISTINCT from_node_id FROM packet_history WHERE from_node_id IS NOT NULL
                            UNION
                            SELECT DISTINCT to_node_id FROM packet_history WHERE to_node_id IS NOT NULL
                        )
                        LIMIT 1000
                    )
                    """,
                    (cutoff_time,),
                )
                batch_nodes_deleted = cursor.rowcount
                nodes_deleted += batch_nodes_deleted
                conn.commit()
                if batch_nodes_deleted < 1000:
                    break

            if packets_deleted > 0 or nodes_deleted > 0:
                logging.info(
                    f"Cleaned up {packets_deleted} old packets and {nodes_deleted} unused nodes "
                    f"older than {DATA_RETENTION_HOURS} hours"
                )
            else:
                logging.debug(
                    f"No data to clean up (retention: {DATA_RETENTION_HOURS} hours)"
                )

        except Exception as e:
            logging.error(f"Error during data cleanup: {e}")
            # Emit metric for cleanup failure
            try:
                CLEANUP_FAILURES.inc()
            except Exception:
                pass  # Metrics are optional
            conn.rollback()
        finally:
            try:
                cursor.close()
            finally:
                put_db_connection(conn)


def cleanup_worker() -> None:
    """Worker function that runs cleanup periodically in a background thread."""
    logging.info("Cleanup worker thread started")

    # Run cleanup immediately on startup
    cleanup_old_data()

    # Then run cleanup every hour
    while not stop_cleanup.wait(DATA_CLEANUP_INTERVAL_SECONDS):
        cleanup_old_data()

    logging.info("Cleanup worker thread stopped")


def get_node_statistics() -> dict[str, Any]:
    """Get statistics about known nodes."""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Total nodes
            cursor.execute("SELECT COUNT(*) as count FROM node_info")
            total_nodes = cursor.fetchone()["count"]

            # Nodes with names
            cursor.execute("SELECT COUNT(*) as count FROM node_info WHERE long_name IS NOT NULL")
            nodes_with_long_names = cursor.fetchone()["count"]

            # Recent packet senders (last 24 hours)
            twenty_four_hours_ago = time.time() - (24 * 3600)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT from_node_id) as count
                FROM packet_history
                WHERE timestamp > %s AND from_node_id IS NOT NULL
            """,
                (twenty_four_hours_ago,),
            )
            active_nodes_24h = cursor.fetchone()["count"]

            # Total packets received
            cursor.execute("SELECT COUNT(*) as count FROM packet_history")
            total_packets = cursor.fetchone()["count"]

            return {
                "total_nodes": total_nodes,
                "nodes_with_long_names": nodes_with_long_names,
                "active_nodes_24h": active_nodes_24h,
                "total_packets": total_packets,
            }
        finally:
            try:
                cursor.close()
            finally:
                put_db_connection(conn)


def format_hop_info(mesh_packet: Any) -> str:
    """Format hop information showing current hop limit and hops traveled."""
    hop_limit = getattr(mesh_packet, "hop_limit", 0)
    hop_start = getattr(mesh_packet, "hop_start", 0)

    if hop_start > 0:
        hops_traveled = hop_start - hop_limit
        if hops_traveled == 0:
            return f"direct (0 hops, TTL: {hop_limit}/{hop_start})"
        else:
            return f"{hops_traveled} hops (TTL: {hop_limit}/{hop_start})"
    else:
        # Fallback if hop_start is not available or is 0
        if hop_limit > 0:
            return f"TTL: {hop_limit} hops remaining"
        else:
            return "direct/unknown hops"


# --- MQTT Functions ---
def on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: dict[str, Any],
    rc: int,
    properties: Any | None = None,
) -> None:
    """Callback for when the client receives a CONNACK response from the server."""
    if rc == 0:
        logging.info(f"Connected successfully to MQTT Broker: {MQTT_BROKER_ADDRESS}")
        # Subscribe to the Meshtastic topics
        topic_to_subscribe = f"{MQTT_TOPIC_PREFIX}{MQTT_TOPIC_SUFFIX}"
        client.subscribe(topic_to_subscribe, qos=MQTT_QOS)
        logging.info(f"Subscribed to MQTT topic: {topic_to_subscribe}")
    else:
        logging.error(f"Failed to connect to MQTT Broker, return code {rc}")
        if rc == 3:
            logging.error("Connection refused: Server unavailable.")
        elif rc == 4:
            logging.error("Connection refused: Bad username or password.")
        elif rc == 5:
            logging.error("Connection refused: Not authorized.")
        else:
            logging.error("Connection refused: Unknown reason.")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Callback for when a PUBLISH message is received from the server."""
    process_start = time.perf_counter()
    processed_successfully = False
    parsing_error = None
    message_type = None
    span = None
    span_cm = TRACER.start_as_current_span(
        "mqtt.on_message",
        attributes={
            "mqtt.topic": msg.topic,
            "mqtt.qos": getattr(msg, "qos", None),
        },
    )

    with span_cm as span:
        logging.debug(f"Received message on topic {msg.topic}: {len(msg.payload)} bytes")

        with ingest_stats_lock:
            ingest_stats["received"] += 1
        PACKETS_RECEIVED.inc()

        # Skip JSON messages - we only want protobuf messages
        if "/json/" in msg.topic:
            logging.debug(f"Skipping JSON message on topic {msg.topic}")
            if span is not None:
                span.set_attribute("malla.packet.skipped", True)
            return

        # Skip status/housekeeping topics that don't carry ServiceEnvelope protobufs
        topic_parts = msg.topic.split("/")
        if len(topic_parts) >= 4 and topic_parts[3] == "stat":
            logging.debug(f"Skipping status topic (no protobuf expected): {msg.topic}")
            if span is not None:
                span.set_attribute("malla.packet.skipped", True)
            return

        logging.debug(f"Processing protobuf message on topic {msg.topic}")

        # Always store the raw message data first, regardless of parsing success
        raw_service_envelope_data = msg.payload
        service_envelope = None
        mesh_packet = None

        # Extract message type from topic for logging
        topic_parts = []
        try:
            topic_parts = msg.topic.split("/")
            if len(topic_parts) >= 4:
                message_type = topic_parts[3]  # Should be 'e', 'c', 'p', etc.
                logging.debug(f"Message type from topic: {message_type}")
        except Exception:
            pass

    try:
        # Attempt to parse the ServiceEnvelope
        service_envelope = mqtt_pb2.ServiceEnvelope()
        service_envelope.ParseFromString(msg.payload)
        mesh_packet = service_envelope.packet

        from_node_id_numeric = getattr(mesh_packet, "from")
        to_node_id_numeric = mesh_packet.to

        # Try to decrypt the packet if it appears to be encrypted
        # Check if this is an UNKNOWN_APP packet that might be encrypted
        is_encrypted_packet = (
            hasattr(mesh_packet, "decoded")
            and mesh_packet.decoded.portnum == portnums_pb2.PortNum.UNKNOWN_APP
            and hasattr(mesh_packet, "encrypted")
            and mesh_packet.encrypted
        )

        if is_encrypted_packet:
            logging.debug(
                f"Attempting to decrypt UNKNOWN_APP packet {mesh_packet.id} from {from_node_id_numeric}"
            )

            # Extract channel name from topic if available (for key derivation)
            # Topic format: msh/region/gateway_id/message_type/channel_name/gateway_hex
            channel_name = ""
            try:
                if len(topic_parts) >= 5:
                    # The 5th part (index 4) might be channel name like "LongFast"
                    potential_channel = topic_parts[4]
                    if not potential_channel.startswith("!"):
                        channel_name = potential_channel
                        logging.debug(f"Using channel name from topic: {channel_name}")
            except Exception:
                pass

            # Try decryption with primary channel keys (most common case)
            decryption_successful = try_decrypt_mesh_packet(
                mesh_packet, channel_name=""
            )
            with ingest_stats_lock:
                if decryption_successful:
                    ingest_stats["decrypt_success"] += 1
                else:
                    ingest_stats["decrypt_failed"] += 1
            if decryption_successful:
                PACKETS_DECRYPT_SUCCESS.inc()
            else:
                PACKETS_DECRYPT_FAILED.inc()

            # If primary channel decryption failed and we have a channel name, try with channel-specific keys
            if not decryption_successful and channel_name:
                logging.debug(
                    f"Primary channel decryption failed, trying channel-specific keys for: {channel_name}"
                )
                decryption_successful = try_decrypt_mesh_packet(
                    mesh_packet,
                    channel_name=channel_name,
                )
                with ingest_stats_lock:
                    if decryption_successful:
                        ingest_stats["decrypt_success"] += 1
                    else:
                        ingest_stats["decrypt_failed"] += 1
                if decryption_successful:
                    PACKETS_DECRYPT_SUCCESS.inc()
                else:
                    PACKETS_DECRYPT_FAILED.inc()

            if decryption_successful:
                logging.info(
                    f"Successfully decrypted packet from {get_node_display_name(from_node_id_numeric)}"
                )
            else:
                logging.debug(
                    f"Could not decrypt packet {mesh_packet.id} from {from_node_id_numeric}"
                )

        # Update node cache with gateway hex ID if we can determine the numeric ID
        if service_envelope.gateway_id:
            gateway_numeric_id = hex_id_to_numeric(service_envelope.gateway_id)
            if gateway_numeric_id and gateway_numeric_id not in node_cache:
                # Add minimal entry for the gateway so we can track it
                update_node_cache(
                    node_id=gateway_numeric_id, hex_id=service_envelope.gateway_id
                )

        # Process different packet types
        if mesh_packet.decoded.portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
            text_content = mesh_packet.decoded.payload.decode("utf-8", errors="replace")
            from_node_display = get_node_display_name(from_node_id_numeric)
            to_node_display = (
                get_node_display_name(to_node_id_numeric)
                if to_node_id_numeric != 0 and to_node_id_numeric != 0xFFFFFFFF
                else "Broadcast"
            )

            # Build flags display
            flags = []
            if getattr(mesh_packet, "via_mqtt", False):
                flags.append("via MQTT")
            if getattr(mesh_packet, "want_ack", False):
                flags.append("want ACK")
            if getattr(mesh_packet, "pki_encrypted", False):
                flags.append("PKI encrypted")

            flags_str = f" ({', '.join(flags)})" if flags else ""

            logging.info(
                f"Text message from {from_node_display} to {to_node_display}{flags_str}: {text_content[:50]}{'...' if len(text_content) > 50 else ''}"
            )
            processed_successfully = True

        elif mesh_packet.decoded.portnum == portnums_pb2.PortNum.POSITION_APP:
            position_data = mesh_pb2.Position()
            position_data.ParseFromString(mesh_packet.decoded.payload)

            lat = position_data.latitude_i / 1e7
            lon = position_data.longitude_i / 1e7
            alt = position_data.altitude

            from_node_display = get_node_display_name(from_node_id_numeric)
            via_mqtt_str = (
                " (via MQTT)" if getattr(mesh_packet, "via_mqtt", False) else ""
            )
            logging.info(
                f"Position from {from_node_display}{via_mqtt_str}: {lat:.5f}, {lon:.5f} (alt: {alt}m)"
            )
            processed_successfully = True

        elif mesh_packet.decoded.portnum == portnums_pb2.PortNum.NODEINFO_APP:
            user = mesh_pb2.User()
            user.ParseFromString(mesh_packet.decoded.payload)

            node_id_from_payload = user.id
            long_name = user.long_name
            short_name = user.short_name

            hw_model_enum = user.hw_model
            hw_model_str = mesh_pb2.HardwareModel.Name(hw_model_enum).replace(
                "UNSET", "Unknown"
            )

            role_enum = user.role
            role_str = config_pb2.Config.DeviceConfig.Role.Name(role_enum)

            # Update node cache with received nodeinfo
            mac_address = (
                user.macaddr.hex(":")
                if hasattr(user, "macaddr") and user.macaddr
                else None
            )
            update_node_cache(
                node_id=from_node_id_numeric,
                hex_id=node_id_from_payload,
                long_name=long_name if long_name else None,
                short_name=short_name if short_name else None,
                hw_model=hw_model_str,
                role=role_str,
                is_licensed=user.is_licensed,
                mac_address=mac_address,
                primary_channel=service_envelope.channel_id
                if service_envelope
                else None,
            )

            from_node_display = get_node_display_name(from_node_id_numeric)
            via_mqtt_str = (
                " (via MQTT)" if getattr(mesh_packet, "via_mqtt", False) else ""
            )
            logging.info(
                f"NodeInfo for {node_id_from_payload} from {from_node_display}{via_mqtt_str}: {long_name or short_name or 'No name'}"
            )
            processed_successfully = True

        elif mesh_packet.decoded.portnum == portnums_pb2.PortNum.TELEMETRY_APP:
            telemetry_data = telemetry_pb2.Telemetry()
            telemetry_data.ParseFromString(mesh_packet.decoded.payload)

            from_node_display = get_node_display_name(from_node_id_numeric)
            via_mqtt_str = (
                " (via MQTT)" if getattr(mesh_packet, "via_mqtt", False) else ""
            )

            if telemetry_data.HasField("device_metrics"):
                metrics = telemetry_data.device_metrics
                battery = (
                    f"{metrics.battery_level}%"
                    if metrics.HasField("battery_level")
                    else "N/A"
                )
                voltage = (
                    f"{metrics.voltage / 1000.0:.2f}V"
                    if metrics.HasField("voltage")
                    else "N/A"
                )
                logging.info(
                    f"Device telemetry from {from_node_display}{via_mqtt_str}: Battery {battery}, Voltage {voltage}"
                )
            elif telemetry_data.HasField("environment_metrics"):
                metrics = telemetry_data.environment_metrics
                temp = (
                    f"{metrics.temperature:.1f}C"
                    if metrics.HasField("temperature")
                    else "N/A"
                )
                humidity = (
                    f"{metrics.relative_humidity:.1f}%"
                    if metrics.HasField("relative_humidity")
                    else "N/A"
                )
                logging.info(
                    f"Environment telemetry from {from_node_display}{via_mqtt_str}: Temp {temp}, Humidity {humidity}"
                )
            else:
                logging.info(
                    f"Telemetry from {from_node_display}{via_mqtt_str}: Unknown type"
                )

            processed_successfully = True

        elif mesh_packet.decoded.portnum == portnums_pb2.PortNum.MAP_REPORT_APP:
            # Handle MAP_REPORT_APP packets - extract Position data similar to POSITION_APP
            try:
                # MapReport packets contain Position messages
                position_data = mesh_pb2.Position()
                position_data.ParseFromString(mesh_packet.decoded.payload)

                lat = position_data.latitude_i / 1e7 if position_data.latitude_i else None
                lon = position_data.longitude_i / 1e7 if position_data.longitude_i else None
                alt = position_data.altitude if position_data.altitude else None

                from_node_display = get_node_display_name(from_node_id_numeric)
                via_mqtt_str = (
                    " (via MQTT)" if getattr(mesh_packet, "via_mqtt", False) else ""
                )

                if lat is not None and lon is not None:
                    alt_str = f"{alt}m" if alt else "N/A"
                    logging.info(
                        f"MapReport position from {from_node_display}{via_mqtt_str}: {lat:.5f}, {lon:.5f} (alt: {alt_str})"
                    )
                else:
                    logging.info(
                        f"MAP_REPORT from {from_node_display}{via_mqtt_str}: {len(mesh_packet.decoded.payload)} bytes (no position data)"
                    )

                processed_successfully = True
            except Exception as e:
                # If parsing fails, log as generic MAP_REPORT packet
                from_node_display = get_node_display_name(from_node_id_numeric)
                via_mqtt_str = (
                    " (via MQTT)" if getattr(mesh_packet, "via_mqtt", False) else ""
                )
                logging.warning(
                    f"MAP_REPORT from {from_node_display}{via_mqtt_str}: Failed to parse position data: {e}"
                )
                processed_successfully = True  # Still mark as processed to store the packet

        else:
            port_name = portnums_pb2.PortNum.Name(mesh_packet.decoded.portnum)
            from_node_display = get_node_display_name(from_node_id_numeric)
            via_mqtt_str = (
                " (via MQTT)" if getattr(mesh_packet, "via_mqtt", False) else ""
            )

            # If this is still UNKNOWN_APP after decryption attempt, note it
            if mesh_packet.decoded.portnum == portnums_pb2.PortNum.UNKNOWN_APP:
                if is_encrypted_packet:
                    logging.info(
                        f"Encrypted packet {port_name} from {from_node_display}{via_mqtt_str} (decryption failed)"
                    )
                else:
                    logging.info(
                        f"Unknown packet type {port_name} from {from_node_display}{via_mqtt_str}"
                    )
            else:
                logging.info(
                    f"Packet type {port_name} from {from_node_display}{via_mqtt_str}: {len(mesh_packet.decoded.payload) if hasattr(mesh_packet.decoded, 'payload') else 0} bytes"
                )
            processed_successfully = True

    except UnicodeDecodeError as e:
        parsing_error = f"Unicode decode error: {str(e)}"
        logging.warning(f"Could not decode payload as UTF-8 on topic {msg.topic}: {e}")
        with ingest_stats_lock:
            ingest_stats["parse_failed"] += 1
        PACKETS_PARSE_FAILED.inc()
    except Exception as e:
        parsing_error = f"Parsing error: {str(e)}"
        logging.error(
            f"Error processing MQTT protobuf message on topic {msg.topic}: {e}"
        )
        logging.debug(f"Raw payload length: {len(msg.payload)} bytes")
        with ingest_stats_lock:
            ingest_stats["parse_failed"] += 1
        PACKETS_PARSE_FAILED.inc()

    try:
        # Always log packet to database, regardless of parsing success
        try:
            log_packet_to_database(
                msg.topic,
                service_envelope,
                mesh_packet,
                processed_successfully,
                raw_service_envelope_data,
                parsing_error,
            )
        except Exception as db_error:
            logging.error(f"Failed to log packet to database: {db_error}")

        # Log statistics for different message types
        if message_type and processed_successfully:
            if message_type == "e":
                logging.debug("Processed encrypted message")
            elif message_type == "c":
                logging.debug("Processed command message")
            elif message_type == "p":
                logging.debug("Processed position message")
            else:
                logging.debug(f"Processed message type: {message_type}")

        if processed_successfully:
            with ingest_stats_lock:
                ingest_stats["parsed_ok"] += 1
            PACKETS_PARSED.inc()

    finally:
        duration = time.perf_counter() - process_start
        try:
            PACKET_PROCESS_DURATION.labels("on_message").observe(duration)
        except Exception:
            # Metrics are optional; never block processing.
            pass

        if span is not None:
            span.set_attribute("malla.packet.processed_successfully", processed_successfully)
            span.set_attribute("malla.packet.parsing_error", parsing_error or "")
            if message_type is not None:
                span.set_attribute("malla.packet.message_type", message_type)


def on_disconnect(
    client: mqtt.Client,
    userdata: Any,
    flags: dict[str, Any] | None,
    rc: int,
    properties: Any | None = None,
) -> None:
    """Callback for when the client disconnects from the broker."""
    logging.info(f"Disconnected from MQTT Broker with result code {rc}")
    if rc != 0:
        logging.error("Unexpected MQTT disconnection. Will attempt to reconnect.")

        # Implement configurable exponential backoff retry logic
        for attempt in range(MQTT_RECONNECT_MAX_RETRIES):
            delay = min(MQTT_RECONNECT_BASE_DELAY * (2**attempt), MQTT_RECONNECT_MAX_DELAY)
            logging.info(
                f"Reconnection attempt {attempt + 1}/{MQTT_RECONNECT_MAX_RETRIES} in {delay} seconds..."
            )
            time.sleep(delay)

            try:
                logging.info(
                    f"Attempting to reconnect to MQTT broker at {MQTT_BROKER_ADDRESS}:{MQTT_PORT}..."
                )
                client.reconnect()
                logging.info("Successfully reconnected to MQTT broker")
                return
            except ConnectionRefusedError:
                logging.warning(
                    f"Reconnection attempt {attempt + 1} failed: Connection refused"
                )
            except socket.gaierror:
                logging.warning(
                    f"Reconnection attempt {attempt + 1} failed: Cannot resolve hostname"
                )
            except Exception as e:
                logging.warning(f"Reconnection attempt {attempt + 1} failed: {e}")

        logging.error(
            f"Failed to reconnect after {MQTT_RECONNECT_MAX_RETRIES} attempts. Giving up."
        )
    else:
        logging.info("Clean disconnection from MQTT broker")


# --- Main ---
def main() -> None:
    """Main function to start the MQTT client."""
    logging.info("Starting Meshtastic MQTT to PostgreSQL capture tool...")

    # Start Prometheus metrics exporter if enabled
    if METRICS_ENABLED:
        try:
            start_http_server(METRICS_PORT)
            logging.info(f"Metrics exporter started on port {METRICS_PORT}")
        except Exception as exc:  # noqa: BLE001
            logging.warning(f"Failed to start metrics exporter: {exc}")

    # Initialize database and load node cache
    logging.info("Initializing database...")
    init_database()
    load_node_cache()

    # Initialize MQTT Client
    mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2, clean_session=MQTT_CLEAN_SESSION)

    # Configure TLS if enabled
    if MQTT_TLS_ENABLED:
        mqtt_client.tls_set(
            ca_certs=MQTT_TLS_CA_CERT,
            certfile=MQTT_TLS_CLIENT_CERT,
            keyfile=MQTT_TLS_CLIENT_KEY,
        )
        if MQTT_TLS_INSECURE:
            mqtt_client.tls_insecure_set(True)

    if MQTT_USERNAME:
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_disconnect = on_disconnect  # type: ignore[assignment]

    # Attempt to connect
    try:
        logging.info(
            f"Connecting to MQTT broker at {MQTT_BROKER_ADDRESS}:{MQTT_PORT} (keepalive={MQTT_KEEPALIVE}, tls={MQTT_TLS_ENABLED})..."
        )
        mqtt_client.connect(MQTT_BROKER_ADDRESS, MQTT_PORT, MQTT_KEEPALIVE)
    except ConnectionRefusedError:
        logging.error(
            f"Connection to MQTT broker {MQTT_BROKER_ADDRESS}:{MQTT_PORT} refused. Check address/port and broker status."
        )
        return
    except socket.gaierror:
        logging.error(
            f"Cannot resolve hostname for MQTT broker: {MQTT_BROKER_ADDRESS}. Check DNS or network."
        )
        return
    except Exception as e:
        logging.error(f"Failed to connect to MQTT broker: {e}")
        return

    # Start the MQTT client loop
    mqtt_client.loop_start()
    logging.info("MQTT client loop started. Capturing packets to database...")

    # Print initial statistics
    stats = get_node_statistics()
    logging.info(
        f"Database stats: {stats['total_nodes']} nodes, {stats['total_packets']} packets, {stats['active_nodes_24h']} active nodes (24h)"
    )

    # Start the cleanup thread only when enabled
    global cleanup_thread
    if DATA_RETENTION_HOURS > 0:
        stop_cleanup.clear()
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
        logging.info(
            "Data cleanup thread started (interval=%ss, retention=%sh)",
            DATA_CLEANUP_INTERVAL_SECONDS,
            DATA_RETENTION_HOURS,
        )
    else:
        logging.info("Data retention disabled; cleanup worker not started.")

    try:
        # Keep the main thread alive
        while True:
            time.sleep(60)  # Print stats every minute
            stats = get_node_statistics()
            with ingest_stats_lock:
                ingest_snapshot = ingest_stats.copy()
                # Reset counters after reporting
                for k in ingest_stats:
                    ingest_stats[k] = 0
            try:
                ACTIVE_THREADS.set(threading.active_count())
            except Exception:
                pass
            logging.info(
                "Stats: %(total_nodes)s nodes, %(total_packets)s packets, "
                "%(active_nodes_24h)s active (24h) | ingest: "
                "%(received)s received, %(parsed_ok)s ok, %(parse_failed)s failed, "
                "%(decrypt_success)s decrypted, %(decrypt_failed)s decrypt_failed",
                {
                    **stats,
                    **ingest_snapshot,
                },
            )
    except KeyboardInterrupt:
        logging.info("Script interrupted by user. Shutting down...")
    finally:
        # Signal cleanup thread to stop
        stop_cleanup.set()

        # Wait for cleanup thread to finish (with timeout)
        if cleanup_thread and cleanup_thread.is_alive():
            logging.info("Waiting for cleanup thread to finish...")
            cleanup_thread.join(timeout=5)
            if cleanup_thread.is_alive():
                logging.warning("Cleanup thread did not finish gracefully")

        logging.info("Stopping MQTT client loop...")
        mqtt_client.loop_stop()
        logging.info("Disconnecting from MQTT broker...")
        mqtt_client.disconnect()
        logging.info("Meshtastic MQTT to PostgreSQL capture tool stopped.")


if __name__ == "__main__":
    main()
