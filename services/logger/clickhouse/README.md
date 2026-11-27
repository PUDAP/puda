# ClickHouse backend

Requires **PUDA Edge Protocol 1.0**: Python SDK `puda` 0.1.0rc1 or later on the
edges and CLI 0.2.0-rc1 or later. Older edges/clients (0.0.x) are not supported.

- [Server](server/README.md): local, authenticated ClickHouse with persistent data.
- [Logger](logger/README.md): independent NATS subscriptions, E2EE rotation, batched inserts.

Start the server first. Configure and start the logger separately only when ready
to connect to your NATS broker. No NATS endpoint or lab credentials are bundled.

## Upgrading from 0.0.x

Breaking release, no backward compatibility:

- Upgrade edges and clients to Edge Protocol 1.0 first (SDK 0.1.0rc1+, CLI 0.2.0-rc1+).
- Schema: `command_logs` gains `protocol_version` (from `header.protocol_version`;
  there is no per-command version). The legacy `puda.events` table and the
  backfill converter are removed. Use a fresh database; see
  [server/MIGRATION.md](server/MIGRATION.md).
- Telemetry must use the `{timestamp, data}` wrapper; flattened messages are dropped.
- Immediate commands are recorded only from `RESPONSE_IMMEDIATE`; the logger never
  subscribes to `cmd.immediate`, `cmd.ping` or `update` subjects.
- Response streams belong to the provisioner (`setup_streams.sh`). The logger never
  updates or deletes them; a missing one is created with the spec settings
  (interest retention, file storage, 24 h max age) and a warning.
