# Environment Variable Migration Guide

## Required Changes

After the improvements, you **may** need to update your `.env` file depending on your deployment mode.

## Secret Key (IMPORTANT)

### Production Mode
If you're running in **production** (not in development/debug mode), you **must** set a strong secret key:

```bash
# Generate a strong secret key (32+ characters)
# Option 1: Use openssl
openssl rand -hex 32

# Option 2: Use Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Then set in .env
MALLA_SECRET_KEY=your-generated-secret-key-here-minimum-32-characters
```

**Production is detected when:**
- `MALLA_DEBUG=false` (or not set, defaults to false)
- AND `MALLA_ENV` is not set to `"development"`

### Development Mode
If you're running in **development**, you can either:

**Option 1:** Set `MALLA_ENV=development` in your `.env`:
```bash
MALLA_ENV=development
MALLA_DEBUG=true
# Secret key validation is skipped in development mode
```

**Option 2:** Set `MALLA_DEBUG=true`:
```bash
MALLA_DEBUG=true
# Secret key validation is skipped when debug is enabled
```

## Optional: New Environment Variables

You can optionally configure these new settings:

### Performance Tuning
```bash
# Node cache size (default: 10000)
MALLA_NODE_CACHE_MAX_SIZE=10000

# Database connection pool
MALLA_DB_POOL_MIN=1
MALLA_DB_POOL_MAX=50

# Database connection retry settings
MALLA_DB_CONNECT_RETRIES=3
MALLA_DB_CONNECT_RETRY_DELAY=1.0
```

### Production Environment Flag
```bash
# Set to "development" to skip production validations
MALLA_ENV=development
```

## Quick Check

To see if your current setup will work:

1. **Development**: Make sure you have either:
   - `MALLA_DEBUG=true` in your `.env`, OR
   - `MALLA_ENV=development` in your `.env`

2. **Production**: Make sure you have:
   - `MALLA_SECRET_KEY` set to a value that's at least 32 characters long
   - `MALLA_DEBUG=false` (or not set)
   - `MALLA_ENV` not set to "development"

## Migration Steps

1. **Check your current .env file**
2. **If running in production:**
   - Generate a strong secret key (see above)
   - Add `MALLA_SECRET_KEY=<your-generated-key>` to `.env`
3. **If running in development:**
   - Add `MALLA_ENV=development` to `.env` (optional, but recommended)
   - Or ensure `MALLA_DEBUG=true` is set

## Testing Your Configuration

After updating your `.env`, restart your containers:

```bash
docker-compose restart
```

Check the logs for any configuration errors:

```bash
docker-compose logs malla-web | grep -i "config\|secret\|error"
```

If you see a `ConfigurationError` about the secret key, you need to set it properly.
