# ClickHouse backend

- [Server](server/README.md): local, authenticated ClickHouse with persistent data.
- [Logger](logger/README.md): independent NATS subscriptions, E2EE rotation, batched inserts.

Start the server first. Configure and start the logger separately only when ready
to connect to your NATS broker. No NATS endpoint or lab credentials are bundled.
