-- Add cached_longest_links table for performance optimization
-- This table caches the results of expensive longest links analysis
-- to avoid recalculating 25k packets on every request.

CREATE TABLE IF NOT EXISTS cached_longest_links (
    id SERIAL PRIMARY KEY,
    data JSONB NOT NULL,
    calculated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    parameters JSONB NOT NULL,
    CONSTRAINT unique_parameters UNIQUE (parameters)
);

CREATE INDEX IF NOT EXISTS idx_cached_longest_links_time
ON cached_longest_links(calculated_at DESC);

COMMENT ON TABLE cached_longest_links IS 'Caches longest links analysis results to improve performance';
COMMENT ON COLUMN cached_longest_links.data IS 'JSON data containing the longest links analysis results';
COMMENT ON COLUMN cached_longest_links.parameters IS 'JSON parameters used for the analysis (min_distance, min_snr, max_results)';
COMMENT ON COLUMN cached_longest_links.calculated_at IS 'Timestamp when this cache entry was calculated';
