# Malla Project Summary

## What It Is
- Meshtastic MQTT capture + analytics/web UI stack in Python 3.13 (Flask), PostgreSQL-only backend.
- Entrypoints: `malla-capture` (MQTT ingest + DB), `malla-web` (dev Flask), `malla-web-gunicorn` (prod WSGI).
- Config from `config.yaml` or `MALLA_*`; SQLite blocked at runtime; OTLP telemetry optional.

## Runtime Architecture
- App factory (`src/malla/web_ui.py`) wires templates/static, config, telemetry, DB init, cache cleanup thread, health/info endpoints.
- Telemetry via OpenTelemetry (`src/malla/telemetry.py`), Prometheus metrics (capture).
- Database: psycopg2 threaded pool (`src/malla/database/connection.py`) with one-time migrations (primary_channel, BIGINT IDs, packet indexes). Repositories in `src/malla/database/repositories.py` (dashboard, packets, nodes, locations, traceroutes, gateway comparison); optimized packet variant in `packet_repository_optimized.py`.
- Capture daemon (`src/malla/mqtt_capture.py`): MQTT TLS/auth/backoff; protobuf parse/decode; multi-key AES-CTR decryption; node cache; retention worker; logs packets/nodeinfo/telemetry/positions to Postgres.
- Traceroute model/analysis (`src/malla/models/traceroute.py`) builds hop paths, RF hops, distance calc.
- Services layer: analytics, gateways, locations/RF links, nodes, traceroutes/network graphs/longest links, Meshtastic metadata (`src/malla/services/*`).
- Utilities: node name cache/helpers, formatting/markdown filters, traceroute parse/graph, serialization, geo math, decryption helpers, tracing decorator (`src/malla/utils/*`, `tracing_utils.py`).

## Web/UI
- Blueprints registered in `src/malla/routes/__init__.py`: main pages (dashboard/map/chat/live-map/longest-links/line-of-sight), packets + packet detail, nodes, traceroutes, gateway comparison, API.
- Templates under `src/malla/templates/**`; static JS/CSS in `src/malla/static/**` (modern tables, filters, maps, node picker, timezone/dark mode toggles).
- API (`routes/api_routes.py`): stats, analytics, Meshtastic enums, packets (filters/grouping/exclusions), nodes search/list, gateways, traceroute data, map locations/links, signal tables, relay/node analysis; `safe_jsonify` sanitizes NaN/Inf.

## Config & Ops
- Config defaults -> YAML (`config.yaml` or `MALLA_CONFIG_FILE`) -> env overrides; requires Postgres (`MALLA_DATABASE_URL` or host/port creds). MQTT defaults: prefix `msh`, suffix `/+/+/+/#`; TLS and reconnect tuning supported. Data retention + metrics/OTLP toggles.
- Docker Compose stacks provide Postgres + capture + UI (`docker-compose*.yml`); Dockerfile present. Convenience shims `malla-web`, `malla-web-gunicorn`, `malla-capture`.

## Testing & Tooling
- Pytest suite (`tests/`) with unit, integration, API, E2E; fixtures build test SQLite DB; runner `run_tests.py` (install/check/subsets/coverage/parallel). Ruff + basedpyright; Makefile targets for lint/format/test/build; uv for deps.
- Scripts: benchmarks + screenshot generation (`scripts/`).

## Key Files (quick map)
- Config: `src/malla/config.py`, `config.sample.yaml`
- Entrypoints: `src/malla/web_ui.py`, `src/malla/wsgi.py`, `src/malla/mqtt_capture.py`
- DB layer: `src/malla/database/connection.py`, `src/malla/database/repositories.py`, `packet_repository_optimized.py`
- Services: `src/malla/services/*.py`
- Models: `src/malla/models/traceroute.py`
- Routes: `src/malla/routes/*.py`
- Assets/Templates: `src/malla/templates/**`, `src/malla/static/**`
