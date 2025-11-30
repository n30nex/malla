# This module implements application-wide configuration handling.
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AppConfig:
    """Application configuration loaded from YAML and environment variables."""

    # Core UI settings
    name: str = "Malla"
    home_markdown: str = ""

    # Flask/server settings
    secret_key: str | None = None  # Must be explicitly set in production
    database_file: str = "meshtastic_history.db"  # Deprecated: kept for backward compatibility
    host: str = "0.0.0.0"
    port: int = 5008
    debug: bool = False

    # PostgreSQL database settings
    # Either use database_url (connection string) or individual parameters
    database_url: str | None = None  # e.g., "postgresql://user:password@host:port/database"
    database_host: str | None = None
    database_port: int | None = None
    database_name: str | None = None
    database_user: str | None = None
    database_password: str | None = None

    # MQTT capture settings
    mqtt_broker_address: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = "msh"
    mqtt_topic_suffix: str = "/+/+/+/#"
    mqtt_keepalive: int = 60
    mqtt_qos: int = 0
    mqtt_clean_session: bool = True
    mqtt_tls_enabled: bool = False
    mqtt_tls_ca_cert: str | None = None
    mqtt_tls_client_cert: str | None = None
    mqtt_tls_client_key: str | None = None
    mqtt_tls_insecure: bool = False
    mqtt_reconnect_max_retries: int = 10
    mqtt_reconnect_base_delay: int = 1
    mqtt_reconnect_max_delay: int = 60

    # Meshtastic channel default key (for optional packet decryption)
    # Supports comma-separated list of base64-encoded keys
    default_channel_key: str = "1PG7OiApB1nwvP+rz05pAQ=="

    # Ignored node IDs - packets from these nodes will be dropped and not saved to database
    # Supports comma-separated list of node IDs (decimal or hex format like "1127955948" or "!433b3dec" or "433b3dec")
    ignored_node_ids: str = ""

    # Logging
    log_level: str = "INFO"

    # Data cleanup settings
    # Number of hours after which to delete old data (0 = never delete)
    data_retention_hours: int = 0
    # Cleanup interval in seconds (default: 1 hour)
    data_cleanup_interval_seconds: int = 3600

    # Metrics
    metrics_enabled: bool = False
    metrics_port: int = 9100

    # OpenTelemetry settings
    otlp_endpoint: str | None = None

    # Internal attribute to remember the source file used
    _config_path: Path | None = field(default=None, repr=False, compare=False)

    def get_decryption_keys(self) -> list[str]:
        """Parse and return list of decryption keys from the configuration.

        Supports both single keys and comma-separated lists of keys.
        Empty keys are filtered out.

        Returns:
            List of base64-encoded decryption keys
        """
        if not self.default_channel_key:
            return []

        # Split by comma and strip whitespace
        keys = [key.strip() for key in self.default_channel_key.split(",")]

        # Filter out empty keys
        return [key for key in keys if key]

    def get_ignored_node_ids(self) -> set[int]:
        """Parse and return set of ignored node IDs from the configuration.

        Supports comma-separated list of node IDs in decimal or hex format.
        Hex IDs can be prefixed with '!' or not (e.g., "!433b3dec" or "433b3dec").
        Decimal IDs are also supported (e.g., "1127955948").
        Empty values are filtered out.

        Returns:
            Set of numeric node IDs to ignore
        """
        if not self.ignored_node_ids:
            return set()

        ignored_ids = set()
        # Split by comma and strip whitespace
        node_id_strings = [s.strip() for s in self.ignored_node_ids.split(",")]

        for node_id_str in node_id_strings:
            if not node_id_str:
                continue

            try:
                # Try parsing as hex first (with or without ! prefix)
                if node_id_str.startswith("!"):
                    node_id_str = node_id_str[1:]
                # Try hex
                if all(c in "0123456789abcdefABCDEF" for c in node_id_str):
                    node_id = int(node_id_str, 16)
                    ignored_ids.add(node_id)
                else:
                    # Try decimal
                    node_id = int(node_id_str)
                    ignored_ids.add(node_id)
            except ValueError:
                logger.warning(
                    f"Invalid node ID format in ignored_node_ids: {node_id_str}. Skipping."
                )

        return ignored_ids


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------


_YAML_DEFAULT_PATH = "config.yaml"
_ENV_PREFIX = "MALLA_"  # Prefix for environment variable overrides
_DEFAULT_DB_FILE = "meshtastic_history.db"


def _resolve_type(t: Any) -> Any:  # noqa: ANN001
    """Resolve **t** which may be a string forward-reference into a real type."""

    if isinstance(t, str):
        # Basic builtin types are fine to eval() in this restricted context.
        builtins_map = {"bool": bool, "int": int, "float": float, "str": str}
        return builtins_map.get(t, str)
    return t


def _coerce_value(value: str, target_type):  # noqa: ANN001
    """Coerce *value* (a string from env) to *target_type* (which may be a string)."""

    target_type = _resolve_type(target_type)

    try:
        if target_type is bool:
            return value.lower() in {"1", "true", "yes", "on"}
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
    except ValueError:
        logger.warning(
            "Could not coerce environment variable '%s' to %s - using raw string",
            value,
            target_type,
        )
    return value


def load_config(config_path: str | os.PathLike | None = None) -> AppConfig:  # noqa: C901
    """Load configuration in the following precedence order:

    1. Defaults defined in :class:`AppConfig`.
    2. YAML file (``config.yaml`` or path provided via *config_path* or the
       ``MALLA_CONFIG_FILE`` environment variable).
    3. Environment variables prefixed with ``MALLA_`` (e.g. ``MALLA_NAME``)
       - case-insensitive.  **This is the only supported override mechanism.**
    """

    # Step 1 - start with the defaults from the dataclass converted to dict
    data: dict[str, object] = {}

    # Determine the YAML path to use (step 2)
    yaml_path = (
        Path(config_path)  # explicit argument wins
        if config_path is not None
        else Path(os.getenv("MALLA_CONFIG_FILE", _YAML_DEFAULT_PATH))
    )

    if yaml_path.is_file():
        try:
            with yaml_path.open("r", encoding="utf-8") as fp:
                file_data = yaml.safe_load(fp) or {}
            if not isinstance(file_data, dict):
                logger.warning(
                    "YAML config file %s must contain a mapping at top-level - ignoring",
                    yaml_path,
                )
                file_data = {}
            data.update(file_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read YAML config from %s: %s", yaml_path, exc)

    # Step 3 - look for env vars prefixed with MALLA_
    for field_name, field_obj in AppConfig.__dataclass_fields__.items():  # type: ignore[attr-defined]
        env_key = f"{_ENV_PREFIX}{field_name}".upper()
        if env_key in os.environ:
            data[field_name] = _coerce_value(os.environ[env_key], field_obj.type)

    # Construct the config instance
    # If secret_key is not provided, use default only for development
    if "secret_key" not in data:
        data["secret_key"] = None  # Will be validated in validate_config

    try:
        config = AppConfig(**data)  # type: ignore[arg-type]
    except TypeError as e:
        raise ConfigurationError(f"Invalid configuration data: {e}") from e

    config._config_path = yaml_path if yaml_path.is_file() else None

    # Validate configuration immediately after loading
    try:
        validate_config(config)
    except ConfigurationError:
        raise  # Re-raise configuration errors as-is
    except Exception as e:
        raise ConfigurationError(f"Configuration validation failed: {e}") from e

    logger.debug("Loaded application configuration: %s", config)
    return config


def _looks_like_sqlite(cfg: AppConfig) -> bool:
    """Determine if the config points to SQLite (disallowed in Postgres-only mode)."""
    if cfg.database_url and cfg.database_url.startswith("sqlite"):
        return True
    # Explicit database_file set (and not default) implies SQLite usage
    if cfg.database_file and (
        cfg.database_file != _DEFAULT_DB_FILE or os.getenv("MALLA_DATABASE_FILE")
    ):
        return True
    return False


def _is_postgres_url(url: str | None) -> bool:
    """Check if a connection URL uses a PostgreSQL scheme."""
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"postgresql", "postgres"}


def validate_config(cfg: AppConfig) -> None:
    """Validate required configuration and enforce PostgreSQL-only backend.

    Raises:
        ConfigurationError: If configuration is invalid or missing required settings.
    """

    errors: list[str] = []
    allow_sqlite_for_tests = os.getenv("MALLA_ALLOW_SQLITE_FOR_TESTS") == "1"
    is_production = not cfg.debug and os.getenv("MALLA_ENV") != "development"
    service_type = os.getenv("MALLA_SERVICE_TYPE", "web").lower()

    # Security: Require explicit secret key in production (only for web service)
    # The capture service doesn't need Flask's secret key
    if is_production and service_type != "capture":
        if not cfg.secret_key or cfg.secret_key == "dev-secret-key-change-in-production":
            errors.append(
                "MALLA_SECRET_KEY must be explicitly set in production. "
                "Do not use the default secret key."
            )
        elif len(cfg.secret_key) < 32:
            errors.append(
                "MALLA_SECRET_KEY must be at least 32 characters long for security."
            )

    # Database validation
    if not allow_sqlite_for_tests:
        if cfg.database_url and not _is_postgres_url(cfg.database_url):
            errors.append(
                "MALLA_DATABASE_URL must use a PostgreSQL DSN (postgresql:// or postgres://). "
                "SQLite and other backends are unsupported."
            )

        if _looks_like_sqlite(cfg):
            errors.append(
                "SQLite backend is not supported; configure PostgreSQL via MALLA_DATABASE_URL "
                "or MALLA_DATABASE_HOST/PORT/NAME/USER/PASSWORD."
            )

        if not cfg.database_url and not cfg.database_host:
            errors.append(
                "Database configuration missing: set MALLA_DATABASE_URL or "
                "MALLA_DATABASE_HOST/PORT/NAME/USER/PASSWORD."
            )

    # MQTT validation
    if not cfg.mqtt_broker_address:
        errors.append("MQTT broker address is required (MALLA_MQTT_BROKER_ADDRESS).")

    # Port validation
    if cfg.port < 1 or cfg.port > 65535:
        errors.append(f"Invalid port number: {cfg.port}. Must be between 1 and 65535.")

    # Log level validation
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if cfg.log_level.upper() not in valid_log_levels:
        errors.append(
            f"Invalid log level: {cfg.log_level}. Must be one of {valid_log_levels}."
        )

    if errors:
        raise ConfigurationError("Config validation failed:\n - " + "\n - ".join(errors))


# Convenience singleton to avoid re-loading throughout the process
_config_singleton: AppConfig | None = None


def get_config() -> AppConfig:
    """Return a singleton :class:`AppConfig` instance loaded with *load_config()*.
    Subsequent calls return the cached object.
    """

    global _config_singleton  # noqa: PLW0603
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


def describe_database_target(cfg: AppConfig) -> str:
    """Return a human-friendly description of the configured database."""

    if cfg.database_url and _is_postgres_url(cfg.database_url):
        parsed = urlparse(cfg.database_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        dbname = parsed.path.lstrip("/") or "meshtastic_history"
        return f"PostgreSQL at {host}:{port}/{dbname}"

    host = cfg.database_host or "localhost"
    port = cfg.database_port or 5432
    name = cfg.database_name or "meshtastic_history"
    return f"PostgreSQL at {host}:{port}/{name}"


# ---------------------------------------------------------------------------
# Helper for unit tests to override the cached singleton
# ---------------------------------------------------------------------------


def _override_config(new_cfg: AppConfig) -> None:  # noqa: D401, ANN001
    """Force the global singleton to *new_cfg* (used internally by tests)."""

    global _config_singleton  # noqa: PLW0603
    _config_singleton = new_cfg


def _clear_config_cache() -> None:
    """Clear the global config singleton cache (used internally by tests)."""

    global _config_singleton  # noqa: PLW0603
    _config_singleton = None
