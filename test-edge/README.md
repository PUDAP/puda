# test-edge

Software-only PUDA machine for local testing. There is no hardware: commands
update in-memory state and publish telemetry over NATS.

NATS routes by `puda.{machine_id}.*`, so this process runs one edge with one
`MACHINE_ID` (default `test-1`).

## How to use

All commands below are from the **monorepo root**. NATS must be running first.

### 1. Start NATS

```bash
cp infra/nats/.env.example infra/nats/.env
# Set HOST_IP to this machine's LAN/Tailscale IP (or 127.0.0.1 for local-only)
docker compose -f infra/nats/compose.yml up -d
```

The edge creates JetStream streams and KV buckets on connect if they are missing.

### 2. Install and configure

```bash
uv sync
cp test-edge/.env.example test-edge/.env
```

`.env` defaults to `NATS_SERVERS=nats://localhost:4222` and `MACHINE_ID=test-1`.

### 3. Start the edge

```bash
uv run --package test-edge python test-edge/main.py
```

Wait for `Edge Service Ready`. Override the ID with `--id` or `MACHINE_ID`:

```bash
uv run --package test-edge python test-edge/main.py --id test-7
```

From `test-edge/` the same command is `uv run python main.py`.

### 4. Drive the machine

In another terminal.

**PUDA CLI** (pass `--nats-servers` or `puda config set nats_servers nats://localhost:4222`):

```bash
puda machine list --nats-servers nats://localhost:4222
puda machine commands test-1 --nats-servers nats://localhost:4222
puda machine home test-1 --nats-servers nats://localhost:4222
puda machine run test-1 move '{"x":10,"y":20,"z":5}' --nats-servers nats://localhost:4222
puda machine run test-1 echo '{"message":"hello"}' --nats-servers nats://localhost:4222
puda machine run test-1 get_status --nats-servers nats://localhost:4222
puda machine state --nats-servers nats://localhost:4222
puda protocol run --file test-edge/protocol.json --nats-servers nats://localhost:4222
```

`protocol.json` targets `test-1`.

### 5. Docker (optional)

```bash
docker compose -f test-edge/compose.yml up -d --build
```

## Remote commands

| Command | How to invoke | What it does |
| --- | --- | --- |
| `home` | `puda machine home <id>` | Move simulated axes to origin |
| `reset` | `puda machine reset <id>` | Clear homed flag and position |
| `move` | `puda machine run <id> move '{"x":1,"y":2,"z":3}'` | Set absolute `{x,y,z}` |
| `echo` | `puda machine run <id> echo '{"message":"hi"}'` | Round-trip a string |
| `wait` | `puda machine run <id> wait '{"seconds":5}'` | Sleep; useful for BUSY / cancel tests |
| `fail` | `puda machine run <id> fail '{"message":"boom"}'` | Raise so the edge returns `EXECUTION_ERROR` |
| `get_status` | `puda machine run <id> get_status` | Snapshot of homed + position |
| `pause` / `resume` / `cancel` | `puda machine pause\|resume\|cancel <id>` | Immediate-command acknowledgements |
