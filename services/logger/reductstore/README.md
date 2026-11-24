# ReductStore

ReductStore server (`server/`) and NATS logger (`logger/`) for PUDA.

The server stores timestamped JSON blobs. See `logger/README.md` for the NATS → ReductStore logger.

## Running the server

```bash
cd server
cp .env.example .env          # set RS_API_TOKEN
docker compose up -d
```

Data is stored in `server/data` (bind-mounted to `/data` in the container). The `puda` bucket is provisioned at startup via `RS_BUCKET_PUDA_NAME`.

| Variable | Default | Description |
|---|---|---|
| `REDUCTSTORE_PORT` | `8383` | Host port |
| `REDUCTSTORE_BUCKET` | `puda` | Provisioned bucket name |
| `RS_API_TOKEN` | `reduct` | Admin API token |
| `RS_LOG_LEVEL` | `INFO` | Server log level |

The logger's `REDUCTSTORE_TOKEN` must match `RS_API_TOKEN`.
