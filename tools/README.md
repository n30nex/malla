# Development Tools

This directory contains development and maintenance scripts that are not part of the core application.

## Scripts

### Benchmarking
- `benchmark_longest_links.py` - Performance benchmarking for longest links analysis
- `benchmark_map_render.py` - Performance benchmarking for map rendering

### Testing & Documentation
- `generate_screenshots.py` - Generate screenshots for documentation

## Usage

Run scripts with uv from the project root:

```bash
uv run tools/benchmark_longest_links.py
uv run tools/benchmark_map_render.py
uv run tools/generate_screenshots.py
```

## Note

These scripts are for development use only and are not required for running Malla in production.
