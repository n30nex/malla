"""
Export utilities for CSV and JSON data formats.

Provides functions to convert database query results into downloadable formats
for offline analysis in Excel, Python, or other tools.
"""

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any


def format_timestamp_for_export(timestamp: float | None) -> str:
    """Format Unix timestamp to ISO 8601 string for export."""
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, UTC).isoformat()
    except (ValueError, OSError):
        return str(timestamp)


def prepare_row_for_export(row: dict[str, Any]) -> dict[str, Any]:
    """Prepare a database row for export by formatting special types."""
    export_row = {}
    for key, value in row.items():
        # Handle timestamp fields
        if key in ("timestamp", "first_seen", "last_updated", "last_packet_time"):
            export_row[key] = format_timestamp_for_export(value)
        # Handle bytes (convert to hex)
        elif isinstance(value, bytes):
            export_row[key] = value.hex()
        # Handle None values
        elif value is None:
            export_row[key] = ""
        else:
            export_row[key] = value
    return export_row


def generate_csv(data: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    """
    Generate CSV string from list of dictionaries.

    Args:
        data: List of dictionaries representing rows
        columns: Optional list of column names to include (in order).
                If None, uses keys from first row.

    Returns:
        CSV string ready for download
    """
    if not data:
        return ""

    # Prepare data
    prepared_data = [prepare_row_for_export(row) for row in data]

    # Determine columns
    if columns is None:
        columns = list(prepared_data[0].keys()) if prepared_data else []

    # Generate CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")

    writer.writeheader()
    for row in prepared_data:
        writer.writerow(row)

    return output.getvalue()


def generate_json(data: list[dict[str, Any]]) -> str:
    """
    Generate JSON string from list of dictionaries.

    Args:
        data: List of dictionaries representing rows

    Returns:
        JSON string ready for download
    """
    # Prepare data
    prepared_data = [prepare_row_for_export(row) for row in data]

    # Generate JSON with pretty printing
    return json.dumps(prepared_data, indent=2, ensure_ascii=False)


def get_export_filename(base_name: str, format: str, timestamp: bool = True) -> str:
    """
    Generate export filename with optional timestamp.

    Args:
        base_name: Base name for the file (e.g., "packets", "nodes")
        format: File format ("csv" or "json")
        timestamp: Whether to include timestamp in filename

    Returns:
        Formatted filename
    """
    if timestamp:
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"malla_{base_name}_{time_str}.{format}"
    return f"malla_{base_name}.{format}"


def get_content_type(format: str) -> str:
    """Get MIME type for export format."""
    content_types = {
        "csv": "text/csv",
        "json": "application/json",
    }
    return content_types.get(format, "text/plain")
