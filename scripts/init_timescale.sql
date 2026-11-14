-- TimescaleDB Initial Migration & Hypertable Initialization

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Canonical price observations table
CREATE TABLE IF NOT EXISTS price_points_hyper (
    event_time TIMESTAMPTZ NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    external_item_id VARCHAR(128) NOT NULL,
    item_identity_hash CHAR(64) NOT NULL,
    raw_price NUMERIC(12, 4) NOT NULL,
    raw_currency VARCHAR(8) NOT NULL,
    normalized_price NUMERIC(12, 4) NOT NULL,
    base_currency VARCHAR(8) NOT NULL DEFAULT 'USD',
    status VARCHAR(32) NOT NULL DEFAULT 'Fresh',
    confidence NUMERIC(4, 3) NOT NULL DEFAULT 1.000,
    correlation_id VARCHAR(64) NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to TimescaleDB hypertable partitioned by event_time (7-day chunk intervals)
SELECT create_hypertable(
    'price_points_hyper',
    'event_time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Index for instant identity lookups across time
CREATE INDEX IF NOT EXISTS idx_hyper_identity_time 
ON price_points_hyper (item_identity_hash, source_id, event_time DESC);

-- Enable automatic compression on chunks older than 14 days
ALTER TABLE price_points_hyper SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source_id, item_identity_hash',
    timescaledb.compress_orderby = 'event_time DESC'
);

SELECT add_compression_policy('price_points_hyper', INTERVAL '14 days', if_not_exists => TRUE);

-- Retention policy: drop raw ticks older than 30 days
SELECT add_retention_policy('price_points_hyper', INTERVAL '30 days', if_not_exists => TRUE);
