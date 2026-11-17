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

`puda healthcheck` exits nonzero unless `status` is `ok`. Map the JSON report to the next check:

| Report field | Next step |
|---|---|
| `servers[].error` timeout or connection refused | route and listener: `ip route get <broker-ip>`, `scripts/inspect-nats.sh`, `ss -ltnp` on the broker |
| `servers[].error` TLS or certificate | profile `ca` path, `tls://` vs `nats://` scheme, server certificate name/SAN |
| `jetstream.status: failed` | server JetStream configuration and account permissions; `jetstream.error` holds the cause |
| `compatibility.reason: no_responders` | edges, not the broker: edge logs and NATS connection |
| `compatibility.reason: discovery_error` | permissions for `puda.cmd.ping` and `_INBOX` replies; `compatibility.error` holds the cause |

## Heartbeats

Discovery is a lease-like signal, not readiness. Compare the machine timestamp with current UTC time. If cadence is unexpected, inspect the edge telemetry loop and PUDA library timer before changing intervals. Distinguish publisher interval, CLI discovery wait/window, KV expiration, network delay, and stale retained state.
