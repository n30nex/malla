"""
Custom exception hierarchy for Malla application.

This module defines application-specific exceptions that provide better
error handling and more informative error messages.
"""


class MallaError(Exception):
    """Base exception for all Malla-specific errors."""

    pass


class ConfigurationError(MallaError):
    """Raised when configuration is invalid or missing required settings."""

    pass


class DatabaseError(MallaError):
    """Raised when database operations fail."""

    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection cannot be established."""

    pass


class DatabaseQueryError(DatabaseError):
    """Raised when a database query fails."""

    pass


class ValidationError(MallaError):
    """Raised when input validation fails."""

    pass


class SecurityError(MallaError):
    """Raised when security-related operations fail."""

    pass


class MQTTError(MallaError):
    """Raised when MQTT operations fail."""

    pass


class MQTTConnectionError(MQTTError):
    """Raised when MQTT connection cannot be established."""

    pass
