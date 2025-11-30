# Monitoring and Observability Guide

## Metrics

### Prometheus Metrics

Malla exposes Prometheus metrics on the `/metrics` endpoint for both web UI and capture daemon.

#### Web UI Metrics (`http://localhost:5008/metrics`)

- `http_request_duration_seconds`: HTTP request duration histogram
- `http_requests_total`: Total HTTP requests counter
- `api_request_duration_seconds`: API endpoint duration histogram
- `api_requests_total`: Total API requests counter

#### Capture Daemon Metrics (`http://localhost:9100/metrics`)

- `malla_packets_received_total`: MQTT messages received
- `malla_packets_parsed_total`: Packets parsed successfully
- `malla_packets_parse_failed_total`: Packets that failed to parse
- `malla_packets_decrypt_success_total`: Packets decrypted successfully
- `malla_packets_decrypt_failed_total`: Packets failed to decrypt
- `malla_capture_db_query_seconds`: Database operation duration
- `malla_packet_process_seconds`: End-to-end packet processing duration
- `malla_data_cleanup_failures_total`: Data cleanup failures
- `malla_active_threads`: Active threads in capture process
- `malla_mqtt_consumer_lag_seconds`: Time between MQTT message receive and database commit (consumer lag)
- `malla_topic_packets_success_total{topic}`: Packets successfully processed per topic
- `malla_topic_packets_error_total{topic, error_type}`: Packets that failed to process per topic (error types: `parse`, `database`, `processing`)

### Prometheus Configuration

Example `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'malla-web'
    static_configs:
      - targets: ['localhost:5008']
    metrics_path: '/metrics'
    scrape_interval: 15s

  - job_name: 'malla-capture'
    static_configs:
      - targets: ['localhost:9100']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

## Distributed Tracing

### OpenTelemetry Integration

Configure OpenTelemetry by setting `MALLA_OTLP_ENDPOINT`:

```bash
MALLA_OTLP_ENDPOINT=http://your-otel-collector:4317
```

This enables:
- Automatic instrumentation of Flask requests
- Database query tracing
- HTTP client request tracing
- System metrics collection
- Trace context injection into logs

### Trace Correlation

When OpenTelemetry is enabled, trace IDs and span IDs are automatically included in log messages for correlation.

## Logging

### Log Levels

Configure log level via `MALLA_LOG_LEVEL`:
- `DEBUG`: Detailed debugging information
- `INFO`: General informational messages (default)
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical errors

### Log Format

Logs are structured with:
- Timestamp
- Log level
- Logger name (module)
- Message
- Optional trace/span IDs (when OpenTelemetry enabled)

Example:
```
2025-11-30 14:25:24,179 INFO [malla.web_ui] Starting Meshtastic Mesh Health Web UI
```

With tracing:
```
2025-11-30 14:25:24,179 INFO [malla.web_ui] [trace_id=abc123 span_id=def456] Starting Meshtastic Mesh Health Web UI
```

### Log Routing

- INFO/DEBUG → stdout
- WARNING/ERROR/CRITICAL → stderr

This allows easy separation in log aggregation systems.

## Health Checks

### Application Health

Check application health:

```bash
curl http://localhost:5008/health
```

Response:
```json
{
  "status": "healthy",
  "service": "meshtastic-mesh-health-ui",
  "version": "2.0.0"
}
```

### Application Info

Get application information:

```bash
curl http://localhost:5008/info
```

## Alerting Recommendations

### Critical Alerts

1. **Database Connection Failures**
   - Alert when `DatabaseConnectionError` occurs
   - Check database health endpoint

2. **High Error Rate**
   - Alert when error rate > 5% of requests
   - Monitor `http_requests_total{status=~"5.."}`

3. **Slow Response Times**
   - Alert when p95 response time > 5s
   - Monitor `http_request_duration_seconds` histogram

4. **MQTT Connection Issues**
   - Alert when no packets received for > 5 minutes
   - Monitor `malla_packets_received_total` rate

### Warning Alerts

1. **High Memory Usage**
   - Alert when memory > 80% of limit
   - Monitor container memory metrics

2. **Database Query Performance**
   - Alert when query duration > 1s
   - Monitor `malla_capture_db_query_seconds`

3. **Data Cleanup Failures**
   - Alert when cleanup failures increase
   - Monitor `malla_data_cleanup_failures_total`

4. **High Consumer Lag**
   - Alert when consumer lag p95 > 2 seconds
   - Monitor `histogram_quantile(0.95, malla_mqtt_consumer_lag_seconds_bucket)`

5. **Per-Topic Error Rate**
   - Alert when any topic has error rate > 10%
   - Monitor `rate(malla_topic_packets_error_total[5m]) / rate(malla_topic_packets_success_total[5m] + malla_topic_packets_error_total[5m])`

## Grafana Dashboards

### Recommended Panels

1. **Request Rate**: `rate(http_requests_total[5m])`
2. **Error Rate**: `rate(http_requests_total{status=~"5.."}[5m])`
3. **Response Time (p95)**: `histogram_quantile(0.95, http_request_duration_seconds_bucket)`
4. **Packet Processing Rate**: `rate(malla_packets_received_total[5m])`
5. **Database Query Duration**: `histogram_quantile(0.95, malla_capture_db_query_seconds_bucket)`
6. **Active Connections**: `malla_active_threads`
7. **Consumer Lag (p95)**: `histogram_quantile(0.95, malla_mqtt_consumer_lag_seconds_bucket)`
8. **Per-Topic Success Rate**: `rate(malla_topic_packets_success_total[5m])`
9. **Per-Topic Error Rate**: `rate(malla_topic_packets_error_total[5m])`

## Error Tracking

### Sentry Integration (Optional)

To integrate Sentry for error tracking:

1. Install Sentry SDK:
```bash
uv add sentry-sdk[flask]
```

2. Configure in application startup:
```python
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(
    dsn="your-sentry-dsn",
    integrations=[FlaskIntegration()],
    traces_sample_rate=0.1,
    environment="production"
)
```

## Performance Monitoring

### Key Performance Indicators

- **API Response Time**: Target < 1s for 95th percentile
- **Database Query Time**: Target < 500ms for 95th percentile
- **Packet Processing Latency**: Monitor `malla_packet_process_seconds`
- **Consumer Lag**: Target < 1s for 95th percentile (MQTT receive to DB commit)
- **Memory Usage**: Monitor container memory, target < 2GB for web service

### Query Performance

Monitor slow queries:
- Check database slow query log
- Review `malla_capture_db_query_seconds` metrics
- Use `EXPLAIN ANALYZE` for optimization

## Log Aggregation

### Recommended Setup

1. **Docker Logging Driver**: Configure JSON logging driver
2. **Log Forwarding**: Use Fluentd, Fluent Bit, or similar
3. **Centralized Storage**: ELK Stack, Loki, or cloud logging service
4. **Log Retention**: Configure appropriate retention policies

### Docker Logging Configuration

Already configured in `docker-compose.prod.yml`:
- Max log file size: 10MB
- Max log files: 3
- Automatic rotation
