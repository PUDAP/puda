# Single-node NATS with TLS

Optional layout. The default [`../single-node`](../single-node) server stays plaintext.
Use this folder only when every CLI and edge will use the same lab key and CA.

The broker connection is TLS. Payloads are sealed by the clients, not by NATS.
The server certificate does not decrypt those payloads.

## Generate certificates

```bash
cp .env.example .env
# Set HOST_IP to an address clients use to reach this host.
./generate-certs.sh
```

This writes `certs/ca.pem`, `certs/server.pem`, and `certs/server.key`.
It does not write the lab key. Keep `certs/` on the NATS host and give
clients only `ca.pem`.

## Start

```bash
docker compose up -d
```

Clients use `tls://<HOST_IP>:4222`. MQTT listens on `8883` only.
The monitor stays on `127.0.0.1:8222` inside the container.

## JetStream

```bash
cd ../jetstream
NATS_URL=tls://127.0.0.1:4222 NATS_CA=/path/to/certs/ca.pem REPLICAS=1 ./setup_streams.sh
```

## Client settings

On every CLI and edge, before the broker is switched:

```bash
python3 -c 'import os,base64; print("encrypt=" + base64.b64encode(os.urandom(32)).decode())' > e2e.key
chmod 600 e2e.key
```

Copy that same file to every CLI and edge. Do not copy it to the NATS host.

```env
NATS_SERVERS=tls://127.0.0.1:4222
PUDA_NATS_CA=/path/to/certs/ca.pem
PUDA_E2E_KEY_FILE=/path/to/e2e.key
```

Do not put the lab key in `puda.config`.

After the switch, purge `COMMAND_QUEUE`, `COMMAND_IMMEDIATE`,
`RESPONSE_QUEUE`, `RESPONSE_IMMEDIATE`, and the KV buckets
`MACHINE_STATE`, `MACHINE_COMMANDS`, and `LIVESTREAMS`. Clients that have
the key reject leftover plaintext.

## Frame

A sealed payload is:

| Bytes | Meaning |
|---|---|
| 0 | `0xE2` |
| 1 | version `0x01` |
| 2–5 | key id, first 4 bytes of SHA-256 of the 32-byte key |
| 6–17 | 12-byte nonce |
| 18–end | AES-256-GCM ciphertext and 16-byte tag |

The additional data is the NATS subject. KV uses `kv:<bucket>:<key>`.

## MQTT

Connect to `mqtts://<host>:8883` and trust `ca.pem`. TLS ends at the broker.
Seal the JSON yourself with the same frame before publish, and open it after
subscribe. Use the NATS subject as additional data: replace `/` in the MQTT
topic with `.`.

```python
from puda.e2e import open_payload, seal

topic = "puda/pump-1/tlm/heartbeat"
subject = topic.replace("/", ".")
payload = seal(subject, b'{"ok":true}')
plain = open_payload(subject, payload)
```

A client that presents only the server certificate sees ciphertext.
Unsealed JSON is visible to the broker after TLS ends.
