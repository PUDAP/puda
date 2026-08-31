# PUDA load generator

`puda-loadgen` is a Go workload generator for testing PUDA and NATS at fleet
scale. It complements the Python `test-edge` simulator:

- `test-edge`: functional fidelity and driver behavior
- `puda-loadgen`: connection, consumer, telemetry, reconnect, and soak load

## Build

The host does not need Go installed:

```bash
docker build -t puda-loadgen:dev .
```

Or, with Go 1.25+:

```bash
go build -o bin/puda-loadgen ./cmd/puda-loadgen
```

## Modes

### Full fidelity

Creates one NATS connection per virtual edge. The `consumers` and `soak`
scenarios also create one durable queue consumer and one durable immediate
consumer per edge.

```bash
docker run --rm --network host puda-loadgen:dev \
  --edges 10000 \
  --mode full-fidelity \
  --scenario consumers \
  --ramp-duration 5m \
  --duration 30m \
  --nats-servers nats://127.0.0.1:4222
```

### Multiplexed

Represents many machine IDs with a small connection pool. This is useful for
Core NATS telemetry throughput, but does not reproduce per-edge connection or
JetStream consumer cost.

```bash
docker run --rm --network host puda-loadgen:dev \
  --edges 100000 \
  --mode multiplexed \
  --connections 64 \
  --scenario telemetry \
  --heartbeat-interval 10s \
  --position-interval 30s \
  --health-interval 60s \
  --duration 30m \
  --nats-servers nats://127.0.0.1:4222
```

## Scenarios

| Scenario | Connections | Consumers | Heartbeat | Position/health |
|---|---:|---:|---:|---:|
| `connections` | yes | no | no | no |
| `consumers` | yes | 2 per edge | no | no |
| `heartbeat` | yes | no | yes | no |
| `telemetry` | yes | no | yes | yes |
| `soak` | yes | 2 per edge | yes | yes |

`consumers` and `soak` require full-fidelity mode. Consumers bind to
`COMMAND_QUEUE` and `COMMAND_IMMEDIATE` by default; override with
`--queue-stream` and `--immediate-stream` when testing another topology.
Use `soak` rather than `consumers` when exercising CLI operations that first
check heartbeat-based online presence.

Durable consumers created by a run are deleted during normal shutdown by
default. Use `--cleanup-consumers=false` only when deliberately testing offline
backlog or restart behavior, and remove those consumers manually afterward.

Generate one queue command and one immediate command for every edge on a fixed
schedule with `--command-interval`. For example, `--command-interval 5s`
publishes both command types to every edge every five seconds and records their
synthetic responses. This option requires the `consumers` or `soak` scenario.

The current MVP acknowledges received command messages and publishes synthetic
success responses so the PUDA CLI can complete command round trips. It does not
emulate the full PUDA run-state machine or machine-specific driver behavior.
Use `test-edge` for command correctness tests.

## Distributed load

Give each worker a non-overlapping ID range:

```bash
# Worker 1
puda-loadgen --prefix load --start-index 1 --edges 10000 ...

# Worker 2
puda-loadgen --prefix load --start-index 10001 --edges 10000 ...

# Worker 3
puda-loadgen --prefix load --start-index 20001 --edges 10000 ...
```

## Metrics and report

Prometheus metrics are served on `:9090` by default:

```text
GET /metrics
GET /summary
```

Important metrics include:

```text
puda_loadgen_requested_edges
puda_loadgen_edges_online
puda_loadgen_edges_peak
puda_loadgen_consumers
puda_loadgen_messages_sent_total
puda_loadgen_messages_received_total
puda_loadgen_errors_total
puda_loadgen_reconnects_total
```

Write the final summary to a file with:

```bash
puda-loadgen ... --report /results/summary.json
```

## Safety and capacity notes

- A single source IP cannot generally create 100,000 connections to one server
  address because of ephemeral-port limits. Use multiple workers/source IPs.
- Ramp full-fidelity tests gradually; consumer creation is JetStream control
  traffic.
- Consumer cleanup is enabled by default. Still use a dedicated machine-ID
  prefix so interrupted or force-killed runs can be identified and cleaned.
- Monitor NATS `/varz`, `/connz`, `/jsz`, and `/raftz` alongside loadgen metrics.
