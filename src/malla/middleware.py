"""
Input validation middleware for Flask application.

This module provides middleware to validate and sanitize input data
to prevent security issues and data corruption.
"""

import logging
from typing import Any

from flask import Request, g

from .exceptions import ValidationError

logger = logging.getLogger(__name__)


def validate_node_id(node_id: Any) -> int:
    """Validate and convert node ID to integer.

    Args:
        node_id: Node ID value to validate

    Returns:
        Validated integer node ID

    Raises:
        ValidationError: If node ID is invalid
    """
    if node_id is None:
        raise ValidationError("Node ID cannot be None")

    try:
        node_id_int = int(node_id)
        if node_id_int < 0:
            raise ValidationError(f"Node ID must be non-negative, got: {node_id_int}")
        return node_id_int
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid node ID format: {node_id}") from e


def validate_timestamp(timestamp: Any) -> float:
    """Validate and convert timestamp to float.

    Args:
        timestamp: Timestamp value to validate

    Returns:
        Validated float timestamp

    Raises:
        ValidationError: If timestamp is invalid
    """
    if timestamp is None:
        raise ValidationError("Timestamp cannot be None")

    try:
        timestamp_float = float(timestamp)
        if timestamp_float < 0:
            raise ValidationError(f"Timestamp must be non-negative, got: {timestamp_float}")
        return timestamp_float
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid timestamp format: {timestamp}") from e


def validate_limit(limit: Any, max_limit: int = 1000, default: int = 100) -> int:
    """Validate and sanitize pagination limit.

    Args:
        limit: Limit value to validate
        max_limit: Maximum allowed limit
        default: Default limit if not provided

    Returns:
        Validated integer limit

    Raises:
        ValidationError: If limit is invalid
    """
    if limit is None:
        return default

    try:
        limit_int = int(limit)
        if limit_int < 1:
            raise ValidationError(f"Limit must be at least 1, got: {limit_int}")
        if limit_int > max_limit:
            raise ValidationError(f"Limit cannot exceed {max_limit}, got: {limit_int}")
        return limit_int
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid limit format: {limit}") from e


def validate_offset(offset: Any) -> int:
    """Validate and sanitize pagination offset.

    Args:
        offset: Offset value to validate

    Returns:
        Validated integer offset

    Raises:
        ValidationError: If offset is invalid
    """
    if offset is None:
        return 0

    try:
        offset_int = int(offset)
        if offset_int < 0:
            raise ValidationError(f"Offset must be non-negative, got: {offset_int}")
        return offset_int
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid offset format: {offset}") from e


def validate_search_string(search: Any, max_length: int = 100) -> str | None:
    """Validate and sanitize search string.

    Args:
        search: Search string to validate
        max_length: Maximum allowed length

    Returns:
        Validated search string or None

    Raises:
        ValidationError: If search string is invalid
    """
    if search is None or search == "":
        return None

    if not isinstance(search, str):
        search = str(search)

    search = search.strip()
    if len(search) > max_length:
        raise ValidationError(f"Search string cannot exceed {max_length} characters")

    # Remove potentially dangerous characters
    # Allow alphanumeric, spaces, and common punctuation
    if not all(c.isalnum() or c in " .-_@!" for c in search):
        logger.warning(f"Search string contains unusual characters: {search[:50]}")

    return search


def sanitize_gateway_id(gateway_id: Any) -> str | None:
    """Sanitize gateway ID to prevent SQL injection.

    Args:
        gateway_id: Gateway ID to sanitize

    Returns:
        Sanitized gateway ID or None

    Raises:
        ValidationError: If gateway ID is invalid
    """
    if gateway_id is None or gateway_id == "":
        return None

    gateway_id_str = str(gateway_id).strip()
    # Gateway IDs should be alphanumeric with optional special chars
    if len(gateway_id_str) > 100:
        raise ValidationError(f"Gateway ID too long: {len(gateway_id_str)} characters")

    # Remove any characters that could be used for SQL injection
    if any(c in gateway_id_str for c in ["'", '"', ";", "--", "/*", "*/"]):
        raise ValidationError("Gateway ID contains invalid characters")

    return gateway_id_str
