# ClickHouse server

Uses the official `clickhouse/clickhouse-server:26.10.2.103` image pinned to its
multi-platform digest (latest stable release verified on November 4, 2026).
This is a repository configuration update, not an automatic upgrade of an
existing database. Back up and test the official upgrade path for your deployed
version before recreating its container; never delete volumes to upgrade.

HTTP and native ports bind **127.0.0.1 and the LAN IPv4
192.168.50.135**. Override `CLICKHOUSE_LAN_IP` in `.env` when deploying elsewhere
or if DHCP changes this host's address. They do not bind all interfaces.
`nofile=262144`, persistent data/log volumes, authenticated schema healthcheck,
rotated container logs and `restart: unless-stopped` are configured. Background
scheduler pools are bounded for high-core-count development machines.

## Start locally (Docker Compose)

Check `ss -ltn '( sport = :8123 or sport = :9000 )'` and `docker compose ls`
first. Do not reuse another instance's project name, volumes or credentials.

```sh
cd clickhouse/server
cp -n .env.example .env
chmod 600 .env
# Edit .env: replace CLICKHOUSE_PASSWORD with a long random password.
# Generate one with: python3 -c 'import secrets; print(secrets.token_hex(32))'
docker compose config --quiet
docker compose up -d --wait
docker compose ps
# Uses credentials inside the container; no password in shell history.
docker compose exec clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT version(); SHOW TABLES FROM puda" --multiquery'
```

`.env` is ignored by Git. Do not print `docker compose config` without `--quiet`
or share container inspection/environment output: it can reveal credentials.
`CLICKHOUSE_USER=puda` creates a password-protected bootstrap administrator and
removes the passwordless `default` user. Use a separate writer for the logger
when appropriate (create it interactively; do not put real passwords in Git):

```sql
CREATE USER puda_logger IDENTIFIED WITH sha256_password BY 'replace-me';
GRANT INSERT, SELECT ON puda.command_logs TO puda_logger;
GRANT INSERT, SELECT ON puda.telemetry TO puda_logger;
```

The initialization SQL creates `puda.command_logs`, `puda.telemetry` and the
retained legacy `puda.events` only on a **new** data volume.
Changing the SQL is not a migration. To apply additive changes to an existing
instance, review and run them with `clickhouse-client --multiquery`; never delete
volumes to apply a schema change. `CLICKHOUSE_DB` is intentionally fixed to `puda`
in Compose to match the checked-in SQL.

Existing installations must explicitly apply `initdb/002-split-events.sql`
before upgrading the logger/server healthcheck. Follow [MIGRATION.md](MIGRATION.md)
for grants, cutover, optional offline/staged backfill, rollback and idempotency
risks. The new logger never writes the legacy table. Both new tables use monthly
MergeTree partitions with no TTL, retaining `raw_json`; telemetry `data` is JSON
text in a String, not native JSON or fixed cpu/mem/temp columns.

`docker compose stop` preserves data. `docker compose down` removes containers
and the network but preserves named volumes. **`down -v` destroys data.** Back up
volumes before upgrades. Changing `.env` credentials changes the XML user on the
next container recreation; preserve the current `.env` and keep it private.

The published HTTP endpoint is `http://127.0.0.1:8123`; the native endpoint is
`127.0.0.1:9000`. LAN clients use `http://192.168.50.135:8123` or native
`192.168.50.135:9000` with the configured credentials. These endpoints are not
TLS-encrypted; use only on a trusted LAN, do not forward these ports publicly,
and configure TLS/firewall restrictions before using untrusted networks.
The logger Compose uses Linux host networking so it can reach this loopback
endpoint. Other containers need an explicitly configured private network.

## Query examples

```sql
SELECT event_time, machine_id, run_id, cmd_name, step_number, status,
       JSONExtractString(raw_json, 'response', 'message') AS response_message
FROM puda.command_logs
WHERE machine_id = 'robot' AND run_id = 'run-1'
ORDER BY event_time;

SELECT event_time, machine_id, msg_type, stream, data
FROM puda.telemetry
WHERE machine_id = 'robot' ORDER BY event_time DESC LIMIT 100;

SELECT event_time, JSONExtractString(data, 'status') AS status,
       JSONExtractRaw(data, 'nested') AS nested_measurements
FROM puda.telemetry WHERE stream = 'health'
ORDER BY event_time DESC LIMIT 100;

SELECT event_time, user_id, username, cmd_version, cmd_name, status
FROM puda.command_logs WHERE run_id = 'run-1'
ORDER BY event_time;
```

## Official references

- Docker setup: https://clickhouse.com/docs/get-started/setup/self-managed/docker
- Image/initialization: https://clickhouse.com/docs/install/docker
- HTTP confirmation/error handling: https://clickhouse.com/docs/interfaces/http
- Nanosecond conversion: https://clickhouse.com/docs/sql-reference/functions/type-conversion-functions#fromunixtimestamp64nano
