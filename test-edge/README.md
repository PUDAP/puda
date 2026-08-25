# test-edge

Software-only PUDA machine for local testing. There is no hardware: commands
update in-memory state and publish telemetry over NATS.

Each instance needs a unique `MACHINE_ID` because NATS routes by
`puda.{machine_id}.*`. One process can run a single instance or a fleet.

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

`.env` defaults to `NATS_SERVERS=nats://localhost:4222` and `MACHINE_PREFIX=test`.
You do not need to set `MACHINE_ID` unless you want a single pinned name.

### 3. Start instances

```bash
# three machines: test-1, test-2, test-3
uv run --package test-edge python test-edge/main.py --count 3
```

Wait for `Edge Service Ready` on each ID. Other ways to choose IDs:

```bash
# custom prefix → pump-1, pump-2
uv run --package test-edge python test-edge/main.py --count 2 --prefix pump

# explicit names
uv run --package test-edge python test-edge/main.py --ids alpha,beta,gamma

# one machine
uv run --package test-edge python test-edge/main.py --id test-7
```

From `test-edge/` the same flags work with `uv run python main.py`.
`COUNT`, `MACHINE_IDS`, `MACHINE_ID`, and `MACHINE_PREFIX` in `.env` apply when
the matching flag is omitted.

### 4. Drive the machines

In another terminal.

**Smoke test** (homes, moves, echoes, reads status):

```bash
uv run --package test-edge python test-edge/smoke_test.py --count 3
uv run --package test-edge python test-edge/smoke_test.py --ids alpha,beta
```

**PUDA CLI** (pass `--nats-servers` or `puda config set nats_servers nats://localhost:4222`):

```bash
puda machine list --nats-servers nats://localhost:4222
puda machine commands test-1 --nats-servers nats://localhost:4222
puda machine home test-1 test-2 test-3 --nats-servers nats://localhost:4222
puda machine run test-2 move '{"x":10,"y":20,"z":5}' --nats-servers nats://localhost:4222
puda machine run test-2 echo '{"message":"hello"}' --nats-servers nats://localhost:4222
puda machine run test-2 get_status --nats-servers nats://localhost:4222
puda machine state --nats-servers nats://localhost:4222
puda protocol run --file test-edge/protocol.json --nats-servers nats://localhost:4222
```

`protocol.json` targets `test-1`. Copy its commands and change `machine_id` to
hit other instances.

### 5. Scale with Docker (optional)

One machine per container. Replica hostnames become `test-1` … `test-N`:

```bash
docker compose -f test-edge/compose.yml up -d --build --scale edge=5
```

Many IDs in **one** container:

```bash
COUNT=10 docker compose -f test-edge/compose.yml up -d --build
```

Do not combine a large `COUNT` with `--scale` unless you want `COUNT × replicas`
machines.

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
