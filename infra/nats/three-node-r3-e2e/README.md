# Three-node NATS with TLS

Optional layout. The default [`../three-node-r3`](../three-node-r3) cluster
stays plaintext. Use this folder when every CLI and edge will use the same
lab key and CA.

Copy `nats1/`, `nats2/`, and `nats3/` to one host each. Fill each `.env`
before generating certificates. Each server certificate includes that host's
`HOST_IP`, `localhost`, and `127.0.0.1`.

```bash
./generate-certs.sh
```

The script writes one CA and a server certificate under each `natsN/certs/`.
It does not write the lab key. Give clients `ca.pem` only.

On each host:

```bash
cd natsN
cp .env.example .env
docker compose up -d
```

Cluster routes use TLS and require the peer certificate. Client and MQTT
ports match the single-node layout: `4222` and `8883`.

Apply JetStream once:

```bash
cd ../jetstream
NATS_URL=tls://<nats1-host>:4222 NATS_CA=/path/to/ca.pem REPLICAS=3 ./setup_streams.sh
```

Client settings, the sealed frame, and MQTT are the same as
[`../single-node-e2e/README.md`](../single-node-e2e/README.md).
Point `NATS_SERVERS` at all three `tls://` URLs. Do not mix `nats://` and
`tls://` in one list.
