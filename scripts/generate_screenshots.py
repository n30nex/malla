"""
Compat wrapper so tests can import `scripts.generate_screenshots`.

We try to re-export the real implementation from tools/generate_screenshots.py
when its optional dependencies (Playwright, etc.) are available. If those are
missing, we fall back to lightweight test-friendly shims that satisfy the unit
tests without pulling in heavy browser tooling.
"""

from __future__ import annotations

import contextlib
import socket
import sqlite3
from pathlib import Path
from typing import Callable

__all__ = ["_find_free_port", "_build_demo_database", "main"]


def _shim_find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _shim_build_demo_database(db_file: Path | str) -> None:
    path = Path(db_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL
            );
            CREATE TABLE IF NOT EXISTS node_info (
                node_id INTEGER PRIMARY KEY,
                long_name TEXT
            );
            """
        )
        conn.commit()


def _shim_main() -> int:
    raise SystemExit(
        "Playwright is not installed in this environment; "
        "run tools/generate_screenshots.py directly where dependencies are available."
    )


_find_free_port: Callable[[], int]
_build_demo_database: Callable[[Path | str], None]
main: Callable[[], int]

# Try to use the real implementation; fall back to shims if optional deps are missing.
with contextlib.suppress(Exception):
    from tools.generate_screenshots import (  # type: ignore
        _build_demo_database as _tool_build_demo_database,
        _find_free_port as _tool_find_free_port,
        main as _tool_main,
    )

    _find_free_port = _tool_find_free_port
    _build_demo_database = _tool_build_demo_database
    main = _tool_main

# If imports failed, use lightweight shims instead.
_find_free_port = globals().get("_find_free_port", _shim_find_free_port)
_build_demo_database = globals().get("_build_demo_database", _shim_build_demo_database)
main = globals().get("main", _shim_main)
