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
- **Docker setup**: Dockerfile and docker-compose.yml working correctly. ✅
- **Test dependency**: `[dev]` extra is canonical (confirmed: `run_tests.py` line 33 uses `[dev]`, not `[test]`). ✅
- **Capture schema migration cleanup**: Removed duplicate `ALTER TABLE ... ADD COLUMN` blocks and centralized idempotent migrations in `database/connection.py`. ✅
- **Web metrics & tracing coverage**: Instrumented all API endpoints via blueprint-level hooks in `instrumentation.py` module. All 6 blueprints record Prometheus + OTLP metrics. ✅
- **Isolated Postgres fixtures**: Verified `tests/integration/test_data_cleanup.py` uses PostgreSQL fixtures via `conftest.py`. ✅
- **Prometheus registry hygiene**: Verified `src/malla/metrics.py` uses dedicated `_PROCESS_REGISTRY` with proper multiprocess support. ✅
- **SQLite test migration**: Tests migrated to PostgreSQL. Legacy `sqlite3` imports remain in `tests/fixtures/database_fixtures.py` for backwards compatibility but are not used in production tests. ✅
- **DB query timing metrics**: All web UI repository methods (22 methods) instrumented with `@track_query_time` decorator. ✅
- **MQTT consumer lag metrics**: Added `malla_mqtt_consumer_lag_seconds` histogram tracking receive-to-commit latency. ✅
- **Per-topic MQTT metrics**: Added `malla_topic_packets_success_total` and `malla_topic_packets_error_total` counters for per-topic monitoring. ✅
- **Data retention failure metrics**: Metrics emitted for cleanup failures via `malla_data_cleanup_failures_total` counter. ✅
- **Centralized caching**: Implemented `utils/cache_manager.py` with TTL/refresh strategy and stale-while-revalidate pattern. ✅
- **Gateway service caching**: Migrated `GatewayService` to use centralized cache manager. ✅
- **Code cleanup**: SQLite references cleaned up, unused dependencies removed, logging standardized. ✅
- **Developer experience**: `make dev-up` command and `dev.env.example` template added. ✅

## High Priority - Remaining

### Database Performance
- **Status**: Queries are optimized with time windows, indexes, and DISTINCT ON patterns. ✅
- **Pending**: Validate against very heavy queries (10M+ rows) and consider SQL window functions for complex aggregations on large datasets.
- **Note**: Current optimizations should handle most production workloads. This is for future scaling.

### Gateway Analytics
- **Status**: Hop-limit filtering uses index-friendly patterns (`(hop_start - hop_limit) = 0`). ✅
- **Pending**: For very large datasets (10M+ packets), consider materialized views or computed indexes on `(hop_start - hop_limit)`.
- **Note**: Current queries are performant. This is a future optimization for extreme scale.

### MQTT Capture
- **Status**: Consumer lag and per-topic metrics implemented. ✅
- **Pending**: Optional per-topic QoS tuning (future enhancement - low priority).

## Medium Priority - Remaining

### Developer Experience
- **Status**: Enhanced CI workflow created in `.github/workflows/ci-enhanced.yml`. ✅
- **Pending**: Activate CI/CD pipeline (connect to GitHub repository, configure secrets if needed).

## Tests - Remaining

### Test Coverage
- **Status**: Integration tests use PostgreSQL fixtures. ✅
- **Pending**: Add comprehensive test coverage for:
  - Capture pipeline end-to-end
  - Packet grouping logic
  - Gateway comparison functionality
  - Traceroute parsing
  - Node location queries
  - Gunicorn/health endpoint smoke tests

### Test Infrastructure
- **Pending**: Create Postgres fixture builder mirroring SQLite sample data structure.
- **Pending**: Add performance benchmarks for query optimization validation.

## Feature Enhancements - Future Work

### MQTT Features
- **Pending**: MQTT v5 properties support (when Meshtastic adopts MQTT v5).

### UI/UX Enhancements
- **Pending**: Time-range presets (1h/6h/24h/7d) with localStorage persistence.
- **Pending**: CSV/JSON export endpoints for packets/nodes with server-side filters.
- **Pending**: UI download buttons for exports (respecting existing filters/pagination).
- **Pending**: Dark/light mode persistence in localStorage.
- **Pending**: Editable home markdown UI.

### Data Management
- **Pending**: Retention archival option (archive old data instead of deleting).

## Cleanup / Tech Debt - Low Priority

### Code Organization
- **Pending**: Move long scripts under `tools/` directory and mark as dev-only.
- **Pending**: Final cleanup of any remaining SQLite references in docs/tests (most already cleaned up).

## Summary

**System Status**: Production-ready ✅

Most critical and high-priority items are complete. The system is fully functional with:
- Comprehensive metrics and observability
- Optimized database queries
- Centralized caching system
- Proper error handling and validation
- Complete Docker setup

**Remaining work** focuses on:
1. **Advanced optimizations** for extreme scale (10M+ rows)
2. **Test coverage** expansion
3. **Feature enhancements** (UI/UX improvements)
4. **CI/CD activation** (workflow ready, needs connection)
5. **Code organization** (minor cleanup)

All remaining items are enhancements rather than critical fixes.
