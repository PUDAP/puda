# InfluxDB

InfluxDB 3 Core server (`server/`) and Telegraf logger (`logger/`) for PUDA.

The server boots with a preconfigured admin token from a JSON file mounted at `/run/secrets/admin-token`. See `logger/README.md` for the NATS → InfluxDB logger.

## Creating the admin-token file

In InfluxDB 3, `INFLUXDB3_ADMIN_TOKEN_FILE` expects a JSON-formatted file containing token metadata.

`server/compose.yml` bind-mounts `./admin-token.json` to `/run/secrets/admin-token`. Create that file under `server/` before starting the stack.

### Option A: Create the JSON file manually

Create `server/admin-token.json`:

```json
{
  "token": "apiv3_YOUR_GENERATED_SECRET_TOKEN_HERE",
  "name": "admin",
  "description": "Preconfigured bootstrap admin token"
}
```

**Token string rules:**

- Must begin with the `apiv3_` prefix.
- The remainder should be a cryptographically secure random string (at least 16 bytes / 128 bits of entropy):

  ```bash
  echo "apiv3_$(openssl rand -hex 16)"
  ```
- Restrict file permissions locally:

```bash
chmod 644 server/admin-token.json
```

### Option B: Generate automatically via CLI

If you have the `influxdb3` CLI installed, generate a pre-formatted offline JSON file:

```bash
influxdb3 create token --admin \
  --name "admin" \
  --offline \
  --output-file ./server/admin-token.json
```

## What to set for `INFLUXDB_TOKEN`

The `<token>` value in `INFLUXDB_TOKEN` (or `INFLUXDB3_AUTH_TOKEN` for native InfluxDB 3 CLI tools) must be the exact raw token string defined inside your admin-token JSON file.

**Example:** if your JSON file contains:

```json
"token": "apiv3_x9K8mL2pQ5rT7vW1zY3aB5cD7eF9gH0i"
```

then set:

```bash
INFLUXDB_TOKEN=apiv3_x9K8mL2pQ5rT7vW1zY3aB5cD7eF9gH0i
```

Copy `server/.env.example` → `server/.env` (and `logger/.env.example` → `logger/.env`) and replace `<token>` with that same string. The server healthcheck and the Telegraf logger both use `INFLUXDB_TOKEN`.

## Running the server

```bash
cd server
cp .env.example .env          # set INFLUXDB_TOKEN to match admin-token.json
# create admin-token.json (Option A or B above)
docker compose up -d
```

`.env.example` sets Core ingest defaults: 8 IO threads (was 2), 100ms WAL flush, 70% query mem pool, 1h snapshot checkpoints. On a small NAS use `INFLUXDB3_NUM_IO_THREADS=4`. On a 32-core write-heavy box use `12`–`16`. Prefer local NVMe or S3-compatible object storage for the data volume at high ingest; a NAS Docker volume is fine for a lab.

After the logger writes the first `telemetry` row, `influxdb-cache-init` creates a last-value cache `telemetry_last` keyed by `machine_id` (TTL 10 minutes). Fleet “is this machine online?” queries should hit the cache instead of scanning the table:

```sql
SELECT *
FROM last_cache('telemetry', 'telemetry_last')
```

Re-run cache init after a fresh database:

```bash
docker compose up -d --force-recreate influxdb-cache-init
```

Core is still a single node with a ~72 hour query-file window (432 gen1 Parquet files). For HA, compaction, table-level retention, or queries older than that, plan on InfluxDB 3 Enterprise (separate ingest / query / compact nodes) or Cloud. Do not raise `query-file-limit` on Core as a substitute.
