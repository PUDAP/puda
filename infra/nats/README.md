# PUDA NATS infrastructure

Server deployment topology and PUDA JetStream resources are maintained separately:

```text
infra/nats/
├── jetstream/           Canonical PUDA streams, KV buckets, and provisioning
├── single-node/         One NATS server for local development and small tests
├── single-node-e2e/     Same server with TLS, used only when payload encryption is on
├── three-node-r3/       Three physical NATS nodes for an R3 deployment
└── three-node-r3-e2e/   Same cluster with TLS, used only when payload encryption is on
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

## NATS version

All layouts pin `nats:2.15.3`. NATS 2.15 limits each stream to 1000 consumers by
default. PUDA creates one `COMMAND_QUEUE` consumer
per machine, so every `nats.conf` sets `jetstream.limits.default_max_consumers: -1`
(unlimited, the pre-2.15 behaviour). Without it, the 1001st machine cannot
connect.

Upgrading an existing deployment:

- Change the image and `nats.conf` together. NATS 2.14 refuses to start with
  `default_max_consumers` (`unknown field`), and 2.15 without it stops at 1000
  machines.
- Single node: pull both files, then `docker compose up -d`.
- Three-node cluster: NATS recommends 2.15 only from 2.14.7 or later. First restart
  one node at a time on `nats:2.14.10` with the old `nats.conf`, then one node at a
  time on `nats:2.15.3` with the new `nats.conf`. Avoid stream scale or move
  operations until all three nodes run 2.15.
- Downgrading to 2.14: remove `default_max_consumers` first.

See the [NATS 2.15 upgrade guide](https://docs.nats.io/release-notes/upgrade-to-2.15).

## Optional TLS

`single-node-e2e/` and `three-node-r3-e2e/` are the same layouts with TLS on
the client port, cluster routes, and MQTT `8883`. Leave them unused when
clients still dial `nats://`. See
[`single-node-e2e/README.md`](./single-node-e2e/README.md).

Pass `NATS_CA` when provisioning JetStream against a `tls://` URL:

```bash
NATS_URL=tls://127.0.0.1:4222 NATS_CA=/path/to/ca.pem REPLICAS=1 ./setup_streams.sh
```

## PUDA subjects

| Stream | Subjects | Retention |
|---|---|---|
| `COMMAND_QUEUE` | `puda.*.cmd.queue` | workqueue; at most 10 per machine, an 11th publish is refused (`discard_new_per_subject`). Lowering the limit on a live stream deletes the oldest excess commands, so apply it with no runs in progress. |
| `RESPONSE_QUEUE` | `puda.*.cmd.response.queue` | interest (24h max-age) |
| `RESPONSE_IMMEDIATE` | `puda.*.cmd.response.immediate` | interest (24h max-age) |

Immediate commands (`start`, `complete`, `pause`, `resume`, `reset`, `estop`)
use Core NATS request/reply on `puda.*.cmd.immediate`: the edge answers on the
request's inbox and keeps a copy on `RESPONSE_IMMEDIATE`. No stream may capture
`puda.*.cmd.immediate`, and only the edge subscribes to it: any other
subscriber stops the broker answering "no responders" for an offline machine.

Telemetry and events remain on Core NATS. `MACHINE_STATE` and
`MACHINE_COMMANDS` are shared KV buckets keyed by `machine_id`.
`LIVESTREAMS` is a fleet camera registry keyed by stream name; each record
stores the MediaMTX host and the machines that use that feed. The CLI derives
protocol URLs from host + name.
