# TODO / Review Notes

## Critical
- Enforce PostgreSQL-only runtime and validation; SQLite configs are rejected. ✅
- Logging to stdout/stderr; config warning strings fixed. ✅
- Pending: Decide on `[test]` extra vs `[dev]` as canonical (run_tests.py uses `[dev]`).

## High Priority
- Telemetry/Metrics: psycopg2 instrumentation + OTLP wired; Prometheus exporter with ingest/decrypt/parse counters added. Pending: include DB/query timing metrics and packet processing spans.
- MQTT capture: TLS/QoS/keepalive/clean-session and configurable reconnect backoff shipped. Pending: richer metrics (latency/lag) and optional per-topic QoS tuning.
- Database: Indexes for channel_id/gateway_id/to_node_id/portnum_name; grouped queries bounded to last 24h. Pending: validate against heavy queries and consider SQL-side grouping/window functions for large datasets.
- Node/gateway caching: background cleanup exists; pending: centralized TTL/refresh strategy to reduce repeated lookups.
- Data retention: interval configurable and skipped when disabled; pending: emit metrics/alerts on failures.
- Gateway analytics: ensure hop-limit filtering and joins remain performant on large datasets (may need temp/materialized views).
- Security: optional auth still to add.

## Developer Experience
- Pending: one-command dev stack (PG only) and dev.env; clearer config validation messaging; script/Make target to run capture + web under `uv`; CI wiring for lint/tests; README refresh for PG-only + test posture.

## Tests
- Pending: migrate fixtures/tests to PostgreSQL (current SQLite fixtures are legacy) and add coverage for capture pipeline, grouping, gateway comparison, traceroute parsing, node locations, and Gunicorn/health smoke tests.

## Feature Enhancements
- Pending: MQTT v5 properties; UI time-range presets and CSV/JSON export; metrics/spans for web queries; retention archival option; UX polish (dark/light persistence, editable home markdown UI).

## Cleanup / Tech Debt
- Pending: remove or clearly isolate SQLite references in docs/tests; standardize logging format with trace IDs; move long scripts under `tools/` and mark dev-only.
