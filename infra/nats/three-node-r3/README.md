# Three-node NATS cluster with R3 JetStream

Three hosts run one NATS node each. Core NATS connections and traffic are
clustered. The independent `../jetstream/` package provisions PUDA streams and
KV buckets with three replicas so they can survive one node failure.

```text
nats1/
nats2/
nats3/
```

## 1. Place each folder on its host

Copy `nats1/`, `nats2/`, and `nats3/` to their respective hosts. On each host:

```bash
cp .env.example .env
```

Fill in reachable Tailscale/LAN addresses:

| Variable | nats1 | nats2 | nats3 |
|---|---|---|---|
| `HOST_IP` | nats1 IP | nats2 IP | nats3 IP |
| `NATS_PORT` | client port, default `4222` | client port, default `4222` | client port, default `4222` |
| `NATS1_HOST` | derived from `HOST_IP` | nats1 IP | nats1 IP |
| `NATS2_HOST` | nats2 IP | derived from `HOST_IP` | nats2 IP |
| `NATS3_HOST` | nats3 IP | nats3 IP | derived from `HOST_IP` |

`NATS_PORT` controls the host port exposed for client connections and the port
advertised to clients. NATS still listens on `4222` inside each container.
The configured client port, plus `6222`, `8222`, and `1883`, must be reachable
as appropriate.
Route port `6222` must be reachable between all three hosts.

## 2. Start all nodes

On every host:

```bash
docker compose up -d
```

Verify the routes from any node:

```bash
curl -fsS http://localhost:8222/routez |
  jq '[.routes[].remote_id] | unique | length'
```

A fully connected three-node cluster reports two distinct remote server IDs.
The raw route count may be higher because NATS can maintain a route pool to
each peer.

## 3. Provision R3 streams and KV buckets

Resource provisioning is independent of the node folders. From the
repository's `infra/nats/jetstream/` directory, run this once after all three
nodes are healthy:

```bash
NATS_URL=nats://<nats1-ip>:<nats1-port> REPLICAS=3 ./setup_streams.sh
```

The shared stream JSON contains no topology-specific replica count. The setup
command applies R3 consistently to all four streams and both KV buckets.
Do not run the bootstrap independently on all three servers.

If only the individual node folders are copied to their hosts, retain or copy
the separate `jetstream/` directory to an operator host for initial resource
provisioning and future schema updates.

## 4. Verify R3

```bash
nats stream info COMMAND_QUEUE -s nats://<nats1-ip>:<nats1-port>
nats stream info COMMAND_IMMEDIATE -s nats://<nats1-ip>:<nats1-port>
nats kv info MACHINE_STATE -s nats://<nats1-ip>:<nats1-port>
nats kv info MACHINE_COMMANDS -s nats://<nats1-ip>:<nats1-port>
nats kv info LIVESTREAMS -s nats://<nats1-ip>:<nats1-port>
```

Each asset should report three replicas and current followers before it is
considered highly available.

## Client URLs

Configure PUDA clients with all three seed URLs:

```text
nats://<nats1-ip>:<nats1-port>,nats://<nats2-ip>:<nats2-port>,nats://<nats3-ip>:<nats3-port>
```

## Capacity settings per node

- `max_connections`: 200,000
- container `nofile`: 524,288 soft and hard
- `max_ha_assets`: 250,000

`max_ha_assets` only removes a configuration ceiling. Validate memory, disk,
JetStream API latency, restart recovery, and reconnect storms before operating
hundreds of thousands of durable consumers.
