# Malla Architecture Documentation

## Overview

Malla is a Meshtastic MQTT capture and analytics platform that ingests mesh network data into PostgreSQL and provides a comprehensive web UI for analysis.

## System Architecture

### Components

1. **malla-capture**: MQTT message capture daemon
   - Subscribes to Meshtastic MQTT broker
   - Decrypts secondary channel packets (optional)
   - Parses protobuf messages
   - Stores packets and node information in PostgreSQL
   - Runs background data retention cleanup

2. **malla-web**: Flask web application
   - Provides REST API endpoints
   - Serves HTML templates with interactive UI
   - Generates network topology visualizations
   - Exposes Prometheus metrics

3. **PostgreSQL Database**: Data persistence layer
   - Stores packet history and node information
   - Auto-creates schema and indexes on startup
   - Supports time-based data retention

### Data Flow

```
MQTT Broker → malla-capture → PostgreSQL → malla-web → Browser
```

1. MQTT messages arrive at the capture daemon
2. Packets are parsed, decrypted (if keys provided), and stored in PostgreSQL
3. Web UI queries PostgreSQL via repository layer
4. Services layer processes data and generates analytics
5. Routes layer formats responses for API/HTML

## Layer Architecture

### Database Layer (`src/malla/database/`)

- **connection.py**: Connection pooling and schema migrations
- **repositories.py**: Data access objects for each entity type
  - `DashboardRepository`: Dashboard statistics
  - `PacketRepository`: Packet queries and filtering
  - `NodeRepository`: Node information and activity
  - `TracerouteRepository`: Traceroute packet analysis
  - `LocationRepository`: Node location data

### Service Layer (`src/malla/services/`)

Business logic that orchestrates repository calls:
- `LocationService`: Location data with network topology
- `TracerouteService`: Network graph generation
- `GatewayService`: Gateway comparison and analysis
- `NodeService`: Node-related operations
- `AnalyticsService`: Statistical analysis

### Route Layer (`src/malla/routes/`)

HTTP request handling:
- `main_routes.py`: Dashboard, map, chat pages
- `api_routes.py`: REST API endpoints
- `packet_routes.py`: Packet browsing and detail pages
- `node_routes.py`: Node explorer
- `traceroute_routes.py`: Traceroute visualization
- `gateway_routes.py`: Gateway comparison tools

### Configuration

Configuration is loaded in precedence order:
1. Defaults in `AppConfig` dataclass
2. `config.yaml` file (if exists)
3. Environment variables prefixed with `MALLA_`

Production settings are validated at startup and the application will fail fast if required settings are missing or invalid.

## Security Architecture

### Authentication
- Currently no user authentication (acknowledged limitation)
- Intended for internal/trusted network use
- Secret key must be explicitly set in production

### Input Validation
- Middleware validates and sanitizes all input parameters
- SQL queries use parameterized statements
- Node IDs, timestamps, and pagination limits are validated

### Error Handling
- Custom exception hierarchy for different error types
- Global error handlers provide consistent API responses
- Database errors are logged but don't expose sensitive information

## Performance Optimizations

### Database
- Connection pooling (configurable min/max connections)
- Query result caching (30-second TTL for location queries)
- Optimized indexes for common query patterns
- DISTINCT ON queries for latest-per-node lookups

### Memory Management
- LRU cache for node information (configurable max size, default 10k)
- Background cleanup threads for cache maintenance
- Query result pagination to limit memory usage

### API Performance
- Response caching for `/api/locations` endpoint (30 seconds)
- Pagination on all list endpoints
- Pre-computed network topology data shared across requests

## Monitoring & Observability

### Metrics
- Prometheus metrics exposed on `/metrics` endpoint
- HTTP request duration and count metrics
- Database query timing metrics
- Packet processing metrics in capture daemon

### Tracing
- OpenTelemetry integration (optional, via `otlp_endpoint` config)
- Trace context injection into logs
- Distributed tracing for request flows

### Logging
- Structured logging with trace/span IDs when available
- INFO/DEBUG to stdout, WARNING/ERROR to stderr
- Configurable log level

## Deployment Architecture

### Docker Compose
- `postgres`: PostgreSQL 16 database
- `malla-capture`: MQTT capture daemon
- `malla-web`: Flask web application

### Production Considerations
- Use `malla-web-gunicorn` for production WSGI server
- Configure resource limits in Docker
- Set up database backups
- Use secrets management for credentials
- Enable health checks for all services

## Data Model

### packet_history
Stores all captured mesh packets with metadata:
- Timestamp, node IDs, gateway, channel
- RSSI, SNR, hop information
- Raw payload (protobuf bytes)
- Processing status and errors

### node_info
Cached node information:
- Node ID, hex ID, names
- Hardware model, role, license status
- Primary channel, MAC address
- First seen and last updated timestamps

## Extension Points

### Adding New Packet Types
1. Add parsing logic in `mqtt_capture.py` `on_message()` handler
2. Extract relevant fields and store in `packet_history`
3. Add UI display in appropriate template

### Adding New Analytics
1. Create repository method in appropriate repository class
2. Add service method to orchestrate data access
3. Create API endpoint in `api_routes.py`
4. Add UI component if needed

### Custom Integrations
- OpenTelemetry: Configure `otlp_endpoint` for tracing
- Prometheus: Metrics automatically exposed
- Custom exporters: Extend `telemetry.py` or `metrics.py`
