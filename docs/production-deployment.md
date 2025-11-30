# Production Deployment Guide

## Prerequisites

- Docker and Docker Compose installed
- PostgreSQL 13+ (or use provided Docker Compose setup)
- MQTT broker access credentials
- Domain name and SSL certificate (recommended)

## Security Checklist

Before deploying to production:

- [ ] Set `MALLA_SECRET_KEY` to a strong random value (minimum 32 characters)
- [ ] Set `MALLA_DEBUG=false`
- [ ] Configure PostgreSQL with strong password
- [ ] Use TLS for MQTT connection if available
- [ ] Set up firewall rules to restrict access
- [ ] Configure reverse proxy with SSL/TLS
- [ ] Set up database backups
- [ ] Configure log rotation
- [ ] Review and restrict network access

## Configuration

### Required Environment Variables

```bash
# Database (use connection string or individual settings)
MALLA_DATABASE_URL=postgresql://user:password@host:5432/meshtastic_history
# OR
MALLA_DATABASE_HOST=postgres
MALLA_DATABASE_PORT=5432
MALLA_DATABASE_NAME=meshtastic_history
MALLA_DATABASE_USER=postgres
MALLA_DATABASE_PASSWORD=your_secure_password

# MQTT
MALLA_MQTT_BROKER_ADDRESS=mqtt.example.com
MALLA_MQTT_PORT=1883
MALLA_MQTT_USERNAME=your_username
MALLA_MQTT_PASSWORD=your_password

# Security
MALLA_SECRET_KEY=your_very_long_random_secret_key_here_minimum_32_chars
MALLA_DEBUG=false

# Optional: OpenTelemetry
MALLA_OTLP_ENDPOINT=http://your-otel-collector:4317
```

### Production Docker Compose

Use the production override file:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Or set `MALLA_WEB_COMMAND=/app/.venv/bin/malla-web-gunicorn` in your environment.

## Database Setup

### Initial Setup

1. Create database and user:
```sql
CREATE DATABASE meshtastic_history;
CREATE USER malla WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE meshtastic_history TO malla;
```

2. The application will auto-create tables and indexes on first connection.

### Backup Strategy

Set up regular PostgreSQL backups:

```bash
# Daily backup script
pg_dump -h localhost -U malla meshtastic_history > backup_$(date +%Y%m%d).sql
```

Or use PostgreSQL's continuous archiving for point-in-time recovery.

### Data Retention

Configure automatic cleanup:

```bash
MALLA_DATA_RETENTION_HOURS=720  # Keep 30 days of data
```

## Reverse Proxy Setup

### Nginx Example

```nginx
server {
    listen 80;
    server_name malla.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name malla.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:5008;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Monitoring

### Health Checks

Monitor the health endpoint:

```bash
curl http://localhost:5008/health
```

### Metrics

Scrape Prometheus metrics:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'malla-web'
    static_configs:
      - targets: ['localhost:5008']
    metrics_path: '/metrics'

  - job_name: 'malla-capture'
    static_configs:
      - targets: ['localhost:9100']
    metrics_path: '/metrics'
```

### Logging

Configure log aggregation:
- Use Docker logging drivers
- Forward logs to centralized system (ELK, Loki, etc.)
- Set up log rotation to prevent disk fill

## Performance Tuning

### Database Connection Pool

Adjust pool size based on load:

```bash
MALLA_DB_POOL_MIN=5
MALLA_DB_POOL_MAX=50
```

### Node Cache Size

Limit memory usage:

```bash
MALLA_NODE_CACHE_MAX_SIZE=10000  # Default
```

### Gunicorn Workers

For production WSGI server, configure workers:

```bash
# In docker-compose.prod.yml or environment
GUNICORN_WORKERS=4
GUNICORN_THREADS=2
```

## Troubleshooting

### Database Connection Issues

1. Check PostgreSQL is running: `docker-compose ps postgres`
2. Verify connection string format
3. Check firewall rules
4. Review connection pool settings

### High Memory Usage

1. Reduce `MALLA_NODE_CACHE_MAX_SIZE`
2. Enable data retention to limit database size
3. Monitor with `docker stats`

### Slow Queries

1. Check database indexes: `\di` in psql
2. Review slow query logs
3. Consider increasing connection pool
4. Enable query result caching

### MQTT Connection Problems

1. Verify broker address and port
2. Check credentials
3. Review TLS settings if using encrypted connection
4. Check network connectivity

## Maintenance

### Updates

1. Pull latest code
2. Rebuild Docker images: `docker-compose build`
3. Restart services: `docker-compose up -d`
4. Monitor logs for errors

### Database Maintenance

Regular maintenance tasks:
- `VACUUM ANALYZE` to update statistics
- Monitor table sizes
- Review and adjust indexes
- Archive old data if needed

## Disaster Recovery

### Backup Restoration

```bash
psql -h localhost -U malla meshtastic_history < backup.sql
```

### High Availability

For production deployments:
- Use PostgreSQL replication
- Deploy multiple web instances behind load balancer
- Use shared storage for Docker volumes
- Set up automated failover
