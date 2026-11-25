# PUDA logger templates

Services that log PUDA machine traffic from NATS into a database. Each folder
is a self-contained template: a database server stack and a NATS logger.

- `influxdb/`: InfluxDB server and NATS → InfluxDB logger
- `clickhouse/`: ClickHouse server and NATS → ClickHouse logger ([setup](clickhouse/README.md))
- `postgres/`: PostgreSQL server and NATS → PostgreSQL logger
- `reductstore/`: ReductStore server and NATS → ReductStore logger

These are templates for users, not part of the repository's uv workspace. Each
logger pins the published `puda` package from PyPI, so a folder copied into a
deployment repository builds exactly as it does here. To copy one, for example
InfluxDB, from the root of your deployment repository:

```bash
mkdir -p services/influxdb
curl -fsSL https://github.com/PUDAP/puda/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=4 -C services/influxdb puda-main/services/logger/influxdb
```

See [Logging service](https://docs.puda.co/observability/logging-service) for the full setup.
