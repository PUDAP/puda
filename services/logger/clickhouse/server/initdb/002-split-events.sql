CREATE DATABASE IF NOT EXISTS puda;

CREATE TABLE IF NOT EXISTS puda.command_logs
(
    event_id FixedString(64),
    event_ns Int64,
    event_time DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(event_ns, 'UTC'),
    received_ns Int64,
    received_at DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(received_ns, 'UTC'),
    subject String,
    machine_id LowCardinality(String),
    run_id String,
    msg_type LowCardinality(String),
    topic LowCardinality(String),
    cmd_name LowCardinality(String),
    step_number Nullable(Int64),
    username String,
    user_id String,
    cmd_version String,
    status LowCardinality(String),
    raw_json String CODEC(ZSTD(3))
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (machine_id, run_id, event_time, event_id);

CREATE TABLE IF NOT EXISTS puda.telemetry
(
    event_id FixedString(64),
    event_ns Int64,
    event_time DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(event_ns, 'UTC'),
    received_ns Int64,
    received_at DateTime64(9, 'UTC') MATERIALIZED fromUnixTimestamp64Nano(received_ns, 'UTC'),
    subject String,
    machine_id LowCardinality(String),
    msg_type LowCardinality(String),
    topic LowCardinality(String),
    stream LowCardinality(String),
    data String CODEC(ZSTD(3)),
    raw_json String CODEC(ZSTD(3))
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (machine_id, stream, event_time, event_id);
