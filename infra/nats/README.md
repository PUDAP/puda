# PUDA NATS infrastructure

Server deployment topology and PUDA JetStream resources are maintained separately:

```text
infra/nats/
├── jetstream/        Canonical PUDA streams, KV buckets, and provisioning
├── single-node/      One NATS server for local development and small tests
└── three-node-r3/    Three physical NATS nodes for an R3 deployment
```

## JetStream resources

[`jetstream/`](./jetstream/) is the single source of truth for the PUDA command
and response streams. Apply it once per NATS account after the server or cluster
is running, with replication selected explicitly:

```bash
# Single-node deployment
cd jetstream
NATS_URL=nats://localhost:4222 REPLICAS=1 ./setup_streams.sh

# Three-node deployment
cd jetstream
NATS_URL=nats://<nats1-ip>:4222 REPLICAS=3 ./setup_streams.sh
```

## Single node

```bash
cd single-node
cp .env.example .env
# Set HOST_IP in .env
docker compose up -d
```

See [`single-node/README.md`](./single-node/README.md).

## Three-node R3 cluster

Each `natsN/` directory maps to one host, following the layout of
[`PUDAP/puda-nats-template`](https://github.com/PUDAP/puda-nats-template):

```text
three-node-r3/nats1/
three-node-r3/nats2/
three-node-r3/nats3/
```

See [`three-node-r3/README.md`](./three-node-r3/README.md).

## PUDA subjects

| Stream | Subjects | Retention |
|---|---|---|
| `COMMAND_QUEUE` | `puda.*.cmd.queue` | workqueue |
| `COMMAND_IMMEDIATE` | `puda.*.cmd.immediate` | workqueue |
| `RESPONSE_QUEUE` | `puda.*.cmd.response.queue` | interest (24h max-age) |
| `RESPONSE_IMMEDIATE` | `puda.*.cmd.response.immediate` | interest (24h max-age) |

Telemetry and events remain on Core NATS. `MACHINE_STATE` and
`MACHINE_COMMANDS` are shared KV buckets keyed by `machine_id`.
