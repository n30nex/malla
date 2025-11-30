# Troubleshooting Guide

## Common Issues

### Application Won't Start

**Symptom**: Application exits immediately or fails to start

**Solutions**:
1. Check configuration validation errors in logs
2. Verify `MALLA_SECRET_KEY` is set in production (minimum 32 characters)
3. Ensure database is accessible and credentials are correct
4. Check that required environment variables are set

### Database Connection Errors

**Symptom**: `DatabaseConnectionError` or connection timeouts

**Solutions**:
1. Verify PostgreSQL is running: `docker-compose ps postgres`
2. Check connection string format: `postgresql://user:pass@host:port/db`
3. Verify network connectivity between containers
4. Check firewall rules
5. Review connection pool settings (`MALLA_DB_POOL_MIN`, `MALLA_DB_POOL_MAX`)
6. Enable connection retry (already configured, check retry count)

### Slow API Responses

**Symptom**: API endpoints take >5 seconds to respond

**Solutions**:
1. Check database query performance:
   - Review slow query logs
   - Verify indexes exist: `\di` in psql
   - Run `EXPLAIN ANALYZE` on slow queries
2. Enable query result caching (already implemented)
3. Check database connection pool size
4. Monitor database CPU and memory usage
5. Consider increasing `MALLA_DB_POOL_MAX`

### High Memory Usage

**Symptom**: Container memory usage grows over time

**Solutions**:
1. Reduce node cache size: `MALLA_NODE_CACHE_MAX_SIZE=5000`
2. Enable data retention: `MALLA_DATA_RETENTION_HOURS=720`
3. Monitor with `docker stats`
4. Check for memory leaks in logs
5. Restart services periodically if needed

### MQTT Connection Issues

**Symptom**: No packets being captured

**Solutions**:
1. Verify MQTT broker address and port
2. Check MQTT credentials
3. Review topic prefix/suffix settings
4. Test MQTT connection manually: `mosquitto_sub -h broker -t 'msh/+/+/+/#'`
5. Check TLS settings if using encrypted connection
6. Review MQTT reconnect settings

### Missing Data

**Symptom**: Expected packets or nodes not appearing

**Solutions**:
1. Check data retention settings (may be deleting data)
2. Verify MQTT subscription is working
3. Check packet parsing errors in capture logs
4. Verify decryption keys if using secondary channels
5. Check database for failed packet inserts

### Query Performance Issues

**Symptom**: Specific queries are slow (e.g., `/api/locations`)

**Solutions**:
1. Check if indexes exist for the query
2. Review query execution plan: `EXPLAIN ANALYZE`
3. Consider adding time filters to limit data scan
4. Enable query caching (already implemented for locations)
5. Monitor database statistics and update if stale: `ANALYZE`

## Debugging

### Enable Debug Logging

```bash
MALLA_LOG_LEVEL=DEBUG
```

### Check Application Health

```bash
curl http://localhost:5008/health
curl http://localhost:5008/info
```

### View Metrics

```bash
# Web UI metrics
curl http://localhost:5008/metrics

# Capture daemon metrics
curl http://localhost:9100/metrics
```

### Database Inspection

```bash
# Connect to database
docker-compose exec postgres psql -U postgres meshtastic_history

# Check table sizes
SELECT pg_size_pretty(pg_total_relation_size('packet_history'));
SELECT pg_size_pretty(pg_total_relation_size('node_info'));

# Check recent packets
SELECT COUNT(*) FROM packet_history WHERE timestamp > extract(epoch from now() - interval '1 hour');

# Check indexes
\di
```

### Log Analysis

```bash
# View all logs
docker-compose logs

# Follow logs
docker-compose logs -f malla-web
docker-compose logs -f malla-capture

# Filter for errors
docker-compose logs | grep ERROR
```

## Performance Tuning

### Database Tuning

PostgreSQL configuration recommendations:

```conf
# postgresql.conf
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 4MB
min_wal_size = 1GB
max_wal_size = 4GB
```

### Application Tuning

Environment variables for performance:

```bash
# Connection pool
MALLA_DB_POOL_MIN=5
MALLA_DB_POOL_MAX=50

# Cache settings
MALLA_NODE_CACHE_MAX_SIZE=10000

# Query timeouts (if needed)
MALLA_DB_QUERY_TIMEOUT=30
```

## Error Messages

### ConfigurationError

**Cause**: Invalid or missing configuration

**Solution**: Review error message for specific missing/invalid setting

### DatabaseConnectionError

**Cause**: Cannot connect to PostgreSQL

**Solution**: Check database is running, credentials are correct, network is accessible

### ValidationError

**Cause**: Invalid input parameter

**Solution**: Check API request parameters match expected format

### DatabaseQueryError

**Cause**: Database query failed

**Solution**: Check database logs, verify query syntax, check for constraint violations

## Getting Help

1. Check logs first: `docker-compose logs`
2. Review this troubleshooting guide
3. Check GitHub issues for similar problems
4. Enable debug logging and review detailed error messages
5. Check database and application metrics
