# Malla

Malla (Spanish for "mesh") captures Meshtastic MQTT traffic into PostgreSQL and ships a Flask web UI packed with mesh analytics. Both the capture daemon and the UI read a single config, so you can point them at the same broker/database and get dashboards within minutes.

## Running Instances
- meshtastic.es (Spain): https://malla.meshtastic.es
- malla.ctmesh.org (Connecticut): https://malla.ctmesh.org

## Components
- `malla-capture`: subscribes to your Meshtastic MQTT broker, optionally decrypts secondary channels, and writes packets/node info into PostgreSQL with schema migrations and background data cleanup.
- `malla-web`: Flask UI for dashboards, maps, tables, and diagnostics.
- `malla-web-gunicorn`: production WSGI entry point (used by the `docker-compose.prod.yml` override).
- Database: PostgreSQL 16+ (SQLite is only kept for legacy/test fixtures).

## Features
**Capture pipeline**
- MQTT ingest with auth support, topic prefix/suffix control, and optional multi-key decryption for secondary channels.
- Automatic PostgreSQL schema creation, idempotent migrations, and heavy indexing for fast analytics.
- Background retention worker that prunes stale packets and nodes based on `data_retention_hours`.
- Enriched logging (text, position, telemetry, traceroute, MAP_REPORT) plus hop/gateway metadata.
- Optional OpenTelemetry exporter (`otlp_endpoint`) for traces/metrics.

**Web UI**
- Live dashboard: active/total nodes, packet rates, RF averages, port breakdowns, gateway counts.
- Packet browser: modern table with time/node/gateway/channel/port/RSSI/SNR/hop filters, grouping by `mesh_packet_id`, and detail pages with receptions, payload decode, and traceroute graphs.
- Node explorer: searchable/sortable list with status badges, activity counts, primary channel, and detailed node pages (telemetry, recent packets, location history, relay candidates).
- Maps and topology: location map, live packet flow, traceroute visualizations, network graph, longest links, and line-of-sight explorer.
- Gateway tooling: gateway comparison matrix, direct/relay reception views, hop analysis, and multi-gateway RSSI/SNR deltas.
- Chat view for recent text messages.

## Quick Start (Docker Compose)
The provided compose file runs PostgreSQL, the capture daemon, and the web UI together.

1. Copy and edit your environment:
   ```bash
   cp env.example .env
   $EDITOR .env  # set MALLA_MQTT_* and any MALLA_NAME/SECRET_KEY overrides
   ```
2. Start the stack:
   ```bash
   docker-compose up -d
   ```
   - Default ports: web UI on `http://localhost:5008`, PostgreSQL on `5432`.
   - Data persists in the `postgres_data` volume.
3. Tail logs:
   ```bash
   docker-compose logs -f malla-capture
   docker-compose logs -f malla-web
   ```
4. Production WSGI (Gunicorn):
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   # or set MALLA_WEB_COMMAND=/app/.venv/bin/malla-web-gunicorn in .env
   ```

## Local Development with uv
1. Install uv (if needed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Install dependencies (adds a local `.venv`):
   ```bash
   uv sync --dev
   ```
3. Start or point to PostgreSQL (example):
   ```bash
   docker compose up -d postgres  # uses the included service
   export MALLA_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/meshtastic_history
   ```
4. Create a config and set MQTT:
   ```bash
   cp config.sample.yaml config.yaml
   $EDITOR config.yaml  # set mqtt_broker_address, optional home_markdown, etc.
   ```
5. Run the services (separate terminals):
   ```bash
   uv run malla-capture
   uv run malla-web          # dev server
   # or: uv run malla-web-gunicorn
   ```
6. Custom config path:
   ```bash
   export MALLA_CONFIG_FILE=/path/to/config.yaml
   ```

## Configuration
Configuration is loaded in this order: defaults -> `config.yaml` (or `MALLA_CONFIG_FILE`) -> environment variables prefixed with `MALLA_`. All env vars override YAML.

| Setting | Env var | Default | Purpose |
| --- | --- | --- | --- |
| `name` | `MALLA_NAME` | `"Malla"` | UI display name and browser title |
| `home_markdown` | `MALLA_HOME_MARKDOWN` | `""` | Markdown block on the dashboard |
| `secret_key` | `MALLA_SECRET_KEY` | `"dev-secret-key-change-in-production"` | Flask session key |
| `host` / `port` | `MALLA_HOST` / `MALLA_PORT` | `0.0.0.0` / `5008` | Web bind address/port |
| `debug` | `MALLA_DEBUG` | `false` | Flask debug (development only) |
| `database_url` | `MALLA_DATABASE_URL` | `None` | PostgreSQL connection string (recommended) |
| `database_host` / `database_port` / `database_name` / `database_user` / `database_password` | `MALLA_DATABASE_HOST` / ... | `localhost` / `5432` / `meshtastic_history` / `$USER` / `""` | Used if `database_url` is not set |
| `mqtt_broker_address` | `MALLA_MQTT_BROKER_ADDRESS` | `"127.0.0.1"` | Meshtastic MQTT broker |
| `mqtt_port` | `MALLA_MQTT_PORT` | `1883` | MQTT port |
| `mqtt_username` / `mqtt_password` | `MALLA_MQTT_USERNAME` / `MALLA_MQTT_PASSWORD` | `None` | Optional MQTT auth |
| `mqtt_topic_prefix` / `mqtt_topic_suffix` | `MALLA_MQTT_TOPIC_PREFIX` / `MALLA_MQTT_TOPIC_SUFFIX` | `"msh"` / `"/+/+/+/#"` | Topic selection |
| `default_channel_key` | `MALLA_DEFAULT_CHANNEL_KEY` | `"1PG7OiApB1nwvP+rz05pAQ=="` | Comma-separated base64 keys for decrypting secondary channels |
| `data_retention_hours` | `MALLA_DATA_RETENTION_HOURS` | `0` | Prune packets/nodes older than N hours (0 disables) |
| `log_level` | `MALLA_LOG_LEVEL` | `"INFO"` | Capture service log level |
| `otlp_endpoint` | `MALLA_OTLP_ENDPOINT` | `None` | Enable OTLP tracing/metrics export |

Notes:
- `database_file` still exists for legacy/tests but runtime ingestion/queries expect PostgreSQL.
- Environment variables always win over YAML values.

## Data Retention
Set `data_retention_hours` to automatically delete packet_history rows older than N hours and stale node_info entries with no recent packets. Defaults to `0` (no deletion). Cleanup runs hourly in the capture process.

## Testing
- Install test deps: `python run_tests.py --install`
- Run everything: `python run_tests.py all -v`
- Common subsets: `python run_tests.py unit`, `python run_tests.py integration`, `python run_tests.py api`
- Direct pytest (with uv): `uv run pytest`

## License
MIT License. See `LICENSE` for details.
