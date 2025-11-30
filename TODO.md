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
- **Test dependency**: `[dev]` extra is canonical (confirmed: `run_tests.py` line 33 uses `[dev]`, not `[test]`). ✅

## Next Patch Outline (Phase 2) ✅ COMPLETE
- ✅ **Capture schema migration cleanup**: Removed duplicate `ALTER TABLE ... ADD COLUMN` blocks in `src/malla/mqtt_capture.py` and centralized idempotent migrations in `database/connection.py`.
- ✅ **Web metrics & tracing coverage**: Instrumented all API endpoints via blueprint-level hooks in new `instrumentation.py` module. All 6 blueprints now record Prometheus + OTLP metrics.
- ✅ **Isolated Postgres fixtures**: Verified `tests/integration/test_data_cleanup.py` uses PostgreSQL fixtures via `conftest.py`. No SQLite usage in integration tests.
- ✅ **Prometheus registry hygiene**: Verified `src/malla/metrics.py` uses dedicated `_PROCESS_REGISTRY` with proper multiprocess support. No private registry access.

## Critical

- ~~**SQLite test migration**~~: ✅ Tests migrated to PostgreSQL. Legacy `sqlite3` imports remain in `tests/fixtures/database_fixtures.py` for backwards compatibility but are not used in production tests.

## High Priority

### Telemetry/Metrics
- **Status**: Capture service has DB insert histograms (`DB_QUERY_DURATION`) and OTLP spans (`TRACER.start_as_current_span` in `mqtt_capture.py` line 888). ✅
- **Status**: Web UI now has `/metrics` endpoint exposing Prometheus metrics for all HTTP/API requests. ✅
- **Status**: DB query timing metrics added to all web UI repository methods (22 methods now instrumented with `@track_query_time`). ✅

### MQTT Capture
- **Status**: TLS/QoS/keepalive/clean-session and configurable reconnect backoff shipped. ✅
- **Status**: Consumer lag metric (`malla_mqtt_consumer_lag_seconds`) and per-topic success/error counters (`malla_topic_packets_success_total`, `malla_topic_packets_error_total`) implemented. ✅
- **Pending**: Optional per-topic QoS tuning (future enhancement).

### Database
- **Status**: Indexes for `channel_id`/`gateway_id`/`to_node_id`/`portnum_name` created via migration. ✅
- **Status**: Grouped queries bounded to last 24h. ✅
- **Pending**: Validate against heavy queries and consider SQL-side grouping/window functions for large datasets.

### Node/Gateway Caching
- **Status**: Background cleanup exists in `utils/node_utils.py`. ✅
- **Status**: Centralized TTL/refresh strategy implemented in `utils/cache_manager.py` with stale-while-revalidate pattern. ✅

### Data Retention
- **Status**: Interval configurable and skipped when disabled. ✅
- **Status**: Metrics emitted for cleanup failures via `malla_data_cleanup_failures_total` counter. ✅

### Gateway Analytics
- **Pending**: Ensure hop-limit filtering and joins remain performant on large datasets (may need temp/materialized views).

## Medium Priority

### Code Quality / Cleanup
- **Status**: SQLite references in docstrings already cleaned up (verified). ✅
- **Status**: Unused `opentelemetry-instrumentation-sqlite3` dependency not found in `pyproject.toml` (already removed). ✅
- **Status**: Logging standardized with trace/span IDs via OpenTelemetry instrumentation. ✅

## Developer Experience

- **Status**: `make dev-up` command added to start PostgreSQL and run both capture + web services. ✅
- **Status**: `dev.env.example` template updated with correct `MALLA_DATABASE_URL` and `MALLA_SERVICE_TYPE` variables. ✅
- **Pending**: CI wiring for lint/tests (enhanced CI workflow already created in `.github/workflows/ci-enhanced.yml`).

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
