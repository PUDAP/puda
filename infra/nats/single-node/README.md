# Single-node NATS

Local/development deployment with one NATS 2.14.5 server, JetStream, MQTT,
and NATS UI.

## Start

```bash
cp .env.example .env
# Set HOST_IP to this machine's reachable address.
docker compose up -d
```

## Provision PUDA resources

The canonical stream and KV definitions live in `../jetstream/`:

```bash
cd ../jetstream
NATS_URL=nats://localhost:4222 REPLICAS=1 ./setup_streams.sh
```

This is a cluster-level bootstrap operation, separate from starting the server.
The selected replication factor is explicitly one.

Alternatively, use the `nats-box` command documented in
[`../jetstream/README.md`](../jetstream/README.md).

This layout has no server or JetStream failover. Use `../three-node-r3/` for
production-like HA testing.

## Capacity settings

- `max_connections`: 200,000
- container `nofile`: 524,288 soft and hard
