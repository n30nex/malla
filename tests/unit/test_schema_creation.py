from unittest.mock import MagicMock, patch

import pytest

from src.malla.database.connection import (
    get_db_connection,
)


@pytest.fixture(autouse=True)
def reset_migrations_state():
    """Reset the global migration state before each test."""
    # Reset the global variables in connection.py
    # We need to access them via the module
    import src.malla.database.connection as connection_module

    connection_module._migrations_initialized = False
    connection_module._SCHEMA_MIGRATIONS_DONE.clear()
    connection_module._connection_pool = None
    yield


@patch("src.malla.database.connection.ThreadedConnectionPool")
def test_schema_creation_on_connect(mock_pool_cls):
    """Test that tables are created when connecting to the database."""
    # Setup mock connection and cursor
    mock_pool = MagicMock()
    mock_pool_cls.return_value = mock_pool

    mock_conn = MagicMock()
    mock_pool.getconn.return_value = mock_conn

    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # Call get_db_connection
    # We need to set a dummy DB URL to avoid the SQLite check if defaults are used
    with patch("src.malla.database.connection.get_config") as mock_get_config:
        mock_config = MagicMock()
        mock_config.database_url = "postgresql://user:pass@localhost/db"
        mock_config.database_file = None
        mock_get_config.return_value = mock_config

        conn = get_db_connection()

    # Verify that CREATE TABLE statements were executed
    # We look for partial matches in the execute calls
    create_packet_history_called = False
    create_node_info_called = False

    for call_args in mock_cursor.execute.call_args_list:
        sql = call_args[0][0]
        if "CREATE TABLE IF NOT EXISTS packet_history" in sql:
            create_packet_history_called = True
        if "CREATE TABLE IF NOT EXISTS node_info" in sql:
            create_node_info_called = True

    assert create_packet_history_called, "packet_history table creation not called"
    assert create_node_info_called, "node_info table creation not called"

    # Verify that indexes were created (checking a few key ones)
    create_index_called = False
    for call_args in mock_cursor.execute.call_args_list:
        sql = call_args[0][0]
        if "CREATE INDEX IF NOT EXISTS idx_packet_history_stats" in sql:
            create_index_called = True
            break

    assert create_index_called, "Index creation not called"
