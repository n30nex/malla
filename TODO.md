# TODO / Review Notes

## Completed ✅

- **PostgreSQL-only enforcement**: Runtime validation in `config.py` (`validate_config()`) and `database/connection.py` (`get_db_connection()`) reject SQLite configs. ✅
- **Logging to stdout/stderr**: Implemented in `logging_utils.py` with proper formatting. ✅
- **psycopg2 instrumentation + OTLP**: Full setup in `telemetry.py` with Flask, psycopg2, logging, requests, and system metrics instrumentation. ✅
- **Prometheus metrics in capture**: Counters (packets received/parsed/decrypted), histograms (DB query duration, packet processing), and HTTP exporter on port 9100 in `mqtt_capture.py`. ✅
- **MQTT features**: TLS, QoS, keepalive, clean-session, and configurable reconnect backoff all implemented in `config.py` and used in `mqtt_capture.py`. ✅
- **Database indexes**: Auto-migration in `database/connection.py` creates indexes for `channel_id`, `gateway_id`, `to_node_id`, `portnum_name`. ✅
- **Data retention**: Configurable cleanup with interval control in `mqtt_capture.py` (`cleanup_old_data()`, `cleanup_worker()`). ✅
- **Node/gateway caching**: Background cleanup thread in `utils/node_utils.py` (`start_cache_cleanup()`, `_cache_cleanup_worker()`). ✅
- **Docker setup**: Dockerfile and docker-compose.yml working correctly (recently fixed). ✅

## Critical

- **Test dependency**: `[dev]` extra is canonical (confirmed: `run_tests.py` line 33 uses `[dev]`, not `[test]`). ✅
- **SQLite test migration**: Tests still use SQLite fixtures (`tests/integration/test_data_cleanup.py` imports `sqlite3`). **CRITICAL**: Migrate to PostgreSQL fixtures before removing SQLite support entirely.

## High Priority

### Telemetry/Metrics
- **Status**: Capture service has DB insert histograms (`DB_QUERY_DURATION`) and OTLP spans (`TRACER.start_as_current_span` in `mqtt_capture.py` line 888). ✅
- **Pending**: Web UI lacks query timing metrics/spans. Add Prometheus histograms and OTLP spans for web API queries (similar to capture service).
- **Missing**: No `/metrics` endpoint in web UI. Only capture service exposes Prometheus HTTP server. Add `/metrics` route to web UI for query performance monitoring.

### MQTT Capture
- **Status**: TLS/QoS/keepalive/clean-session and configurable reconnect backoff shipped. ✅
- **Pending**: Richer metrics (latency/lag) and optional per-topic QoS tuning.
- **Enhancement**: Capture consumer lag metric (MQTT receive time vs DB commit) and per-topic success/error counters to spot bad topics rapidly.

### Database
- **Status**: Indexes for `channel_id`/`gateway_id`/`to_node_id`/`portnum_name` created via migration. ✅
- **Status**: Grouped queries bounded to last 24h. ✅
- **Pending**: Validate against heavy queries and consider SQL-side grouping/window functions for large datasets.

### Node/Gateway Caching
- **Status**: Background cleanup exists in `utils/node_utils.py`. ✅
- **Pending**: Centralized TTL/refresh strategy to reduce repeated lookups.

### Data Retention
- **Status**: Interval configurable and skipped when disabled. ✅
- **Pending**: Emit metrics/alerts on failures (currently only logs errors in `mqtt_capture.py` line 1056).

### Gateway Analytics
- **Pending**: Ensure hop-limit filtering and joins remain performant on large datasets (may need temp/materialized views).

## Medium Priority

### Code Quality / Cleanup
- **SQLite references in code**: Remove or update docstrings/comments mentioning SQLite:
  - `src/malla/telemetry.py` line 26: "SQLite3 database operations (optional when using SQLite backend)"
  - `src/malla/mqtt_capture.py` line 16: "python mqtt_to_sqlite.py" (outdated usage comment)
  - `src/malla/__init__.py` line 2: "Malla - Meshtastic MQTT to SQLite capture..." (outdated description)
- **Unused dependency**: `opentelemetry-instrumentation-sqlite3` in `pyproject.toml` line 51 (not needed for PostgreSQL-only runtime).
- **Standardize logging**: Add trace/span IDs and request_id across capture/web; ensure stdout-only formatting matches OTLP expectations.

## Developer Experience

- **Pending**: One-command dev stack (PG only) and `dev.env`; clearer config validation messaging; script/Make target to run capture + web under `uv`; CI wiring for lint/tests; README refresh for PG-only + test posture.
- **Enhancement**: Add `make dev-up` (uv run web + capture) with a seeded Postgres service, plus a `dev.env` template that matches `config.sample.yaml` and auto-exports MALLA vars.

## Tests

- **CRITICAL**: Migrate fixtures/tests to PostgreSQL. Current SQLite fixtures are legacy (`tests/integration/test_data_cleanup.py` uses `sqlite3` directly).
- **Pending**: Add coverage for capture pipeline, grouping, gateway comparison, traceroute parsing, node locations, and Gunicorn/health smoke tests.
- **Enhancement**: Create Postgres fixture builder mirroring SQLite sample data and gate existing tests behind a marker until migration is complete; add a minimal "capture pipeline happy-path" test using the fixture data.

## Feature Enhancements

- **Pending**: MQTT v5 properties; UI time-range presets and CSV/JSON export; retention archival option; UX polish (dark/light persistence, editable home markdown UI).
- **Enhancement**: Add CSV/JSON export endpoints for packets/nodes with server-side filters mirrored from the table, and UI download buttons (respecting existing filters/pagination).
- **Enhancement**: Add a "recent windows" preset selector (1h/6h/24h/7d) shared across map/packets/traceroute views, persisted via localStorage alongside dark-mode preference.

## Cleanup / Tech Debt

- **Pending**: Remove or clearly isolate SQLite references in docs/tests (see Medium Priority section above); move long scripts under `tools/` and mark dev-only.
- **Enhancement**: Mark dev-only scripts under `tools/` directory for better organization.
