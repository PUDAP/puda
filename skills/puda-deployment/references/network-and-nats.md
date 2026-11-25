# Network and NATS SOP

## Separate paths

Document three independent routes:

1. Host to Internet/source repositories.
2. Host/edge to instrument controller.
3. PUDA clients/edges to NATS.

For a dual-NIC host, keep the Internet default route on the intended interface and give the instrument LAN a subnet route with `never-default` semantics. Verify with `ip route get <internet-ip>` and `ip route get <controller-ip>`.

## NATS verification

- Inspect listener: `ss -ltnp`.
- Health endpoint when enabled: `curl --fail http://127.0.0.1:8222/healthz`.
- Test a configured address with a bounded TCP/NATS handshake (`scripts/inspect-nats.sh <host:port>`). It checks only the plaintext `INFO` banner; it does not prove TLS or authentication works.
- From Docker, verify the broker address from the container network. Use host networking only intentionally.
- Remote access requires a routable listener, firewall/routing approval, and authentication/authorization review.
- Treat DHCP, Exanet, VPN, and Tailscale addresses as dynamic; rediscover them.

## Healthcheck failures

`puda healthcheck` exits nonzero unless `status` is `ok`. Read `status` and `issues` first: each issue has a `code`, `target`, `source` (JSON path to the evidence) and a `next_step` to run. Advisory issues never change status. Re-run after a fix; `replica_lagging` right after a node restart clears within seconds.

Common codes: `puda_resources_missing` (run the `setup_streams.sh` command in `next_step`), `puda_resources_under_replicated` (an edge created them with one replica before provisioning; re-run with `REPLICAS=3`), `jetstream_no_quorum` / `puda_resource_no_quorum` (start stopped NATS nodes; three nodes need two), `endpoint_unreachable`, `endpoint_tls_error`.

CLIs older than the `issues` list: map the JSON report to the next check:

| Report field | Next step |
|---|---|
| `servers[].error` timeout or connection refused | route and listener: `ip route get <broker-ip>`, `scripts/inspect-nats.sh`, `ss -ltnp` on the broker |
| `servers[].error` TLS or certificate | profile `ca` path, `tls://` vs `nats://` scheme, server certificate name/SAN |
| `cluster.brokers[].endpoints` has several URLs | normal: one broker configured under several addresses (e.g. LAN and Tailscale). Not a cluster and not an error |
| `jetstream.status: failed` | server JetStream configuration and account permissions; `jetstream.error` holds the cause |
| `compatibility.reason: no_responders` | edges, not the broker: edge logs and NATS connection |
| `compatibility.reason: discovery_error` | permissions for `puda.cmd.ping` and `_INBOX` replies; `compatibility.error` holds the cause |
| `compatibility.machines[].status: unsupported` | the edge's `protocol_version` is missing or not `1.x`: update the PUDA SDK on that machine and restart the edge |

## Heartbeats

Discovery is a lease-like signal, not readiness. Compare the machine timestamp with current UTC time. If cadence is unexpected, inspect the edge telemetry loop and PUDA library timer before changing intervals. Distinguish publisher interval, CLI discovery wait/window, KV expiration, network delay, and stale retained state.
