# Shared PUDA JetStream resources

This directory is independent of NATS server topology. It defines the PUDA
protocol resources that must exist once per NATS account:

- Four command/response streams in `streams/`
- `MACHINE_STATE` KV bucket
- `MACHINE_COMMANDS` KV bucket
- `LIVESTREAMS` KV bucket

The canonical stream JSON intentionally omits `num_replicas`. Replication is a
deployment decision supplied explicitly when applying the resources.

The setup script requires the `nats` CLI and `jq`. The `natsio/nats-box` image
contains both.

## Apply to a single node

```bash
NATS_URL=nats://localhost:4222 REPLICAS=1 ./setup_streams.sh
```

## Apply to a three-node cluster

```bash
NATS_URL=nats://<any-cluster-node>:4222 REPLICAS=3 ./setup_streams.sh
```

`REPLICAS` is required and accepts only `1` or `3`. The same value is applied
to all four streams and the KV buckets, preventing mixed durability.

Before applying a stream, the script uses `jq` to create a temporary effective
config with `num_replicas` injected. The canonical JSON remains independent of
server topology.

Run this bootstrap once per account/cluster—not once on every server. It is
idempotent: existing streams and KV buckets are updated to the requested
replication factor.

## Run through nats-box

From this directory:

```bash
docker run --rm --network host \
  -e NATS_URL=nats://127.0.0.1:4222 \
  -e REPLICAS=1 \
  -e STREAMS_DIR=/streams \
  -v "$PWD/setup_streams.sh:/setup_streams.sh:ro" \
  -v "$PWD/streams:/streams:ro" \
  natsio/nats-box sh /setup_streams.sh
```

Use `REPLICAS=3` for the three-node cluster.
