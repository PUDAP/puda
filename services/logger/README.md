# PUDA logger templates

Services that log PUDA machine traffic from NATS into a database. Each folder
is a self-contained template: a database server stack and a NATS logger.

- `influxdb/`: InfluxDB server and NATS → InfluxDB logger
- `clickhouse/`: ClickHouse server and NATS → ClickHouse logger ([setup](clickhouse/README.md))
- `postgres/`: PostgreSQL server and NATS → PostgreSQL logger
- `reductstore/`: ReductStore server and NATS → ReductStore logger

All four loggers (1.0.0) speak PUDA Edge Protocol 1.0 ([spec](../../docs/edge-protocol/edge-protocol-v1.0.md)): Python SDK `0.1.0rc1`+, CLI `0.2.0-rc1`+, no compatibility with 0.1.x setups (CLI 0.1.x, SDK 0.0.x). See [Upgrading to v0.2.x](https://docs.puda.co/docs/0.2.0/upgrading-to-0.2.x). As observers they:

- never subscribe to `puda.*.cmd.immediate`, `cmd.ping` or `update`, and record immediate commands from `RESPONSE_IMMEDIATE`;
- never update or delete the provisioned response streams (interest retention, 24 h); a missing stream is created with those settings and a warning;
- record `header.protocol_version`, and require the `{timestamp, data}` telemetry wrapper;
- support TLS + payload encryption with `PUDA_NATS_CA` and `PUDA_E2E_KEY_FILE`, following key rotation.

These are templates for users, not part of the repository's uv workspace. Each
logger pins the published `puda` package from PyPI, so a folder copied into a
deployment repository builds exactly as it does here. To copy one, for example
InfluxDB, from the root of your deployment repository:

```bash
mkdir -p services/influxdb
curl -fsSL https://github.com/PUDAP/puda/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=4 -C services/influxdb puda-main/services/logger/influxdb
```

See [Logging service](https://docs.puda.co/docs/0.2.0/observability/logging-service) for the full setup.
