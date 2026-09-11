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
puda machine run test-1 move_to '{"x":10,"y":20,"z":5}' --nats-servers nats://localhost:4222
puda machine run test-1 echo '{"message":"hello"}' --nats-servers nats://localhost:4222
puda machine run test-1 get_status --nats-servers nats://localhost:4222
puda machine state --nats-servers nats://localhost:4222
```

### 5. Clock sync (edge hosts)

On each edge PC, run the scripts in [`chrony/`](chrony/README.md). Pass the
site NTP server IP when you invoke them (do not put it in `.env`).

### 6. Docker (optional)

Starts only the edge. Run the host Chrony script above first if this PC
should lock to the site NTP server.

```bash
docker compose -f test-edge/compose.yml up -d --build
```

## Remote commands

| Command | How to invoke | What it does |
| --- | --- | --- |
| `home` | `puda machine home <id>` | Move simulated axes to origin |
| `reset` | `puda machine reset <id>` | Clear homed flag, heater, and position |
| `move_to` | `puda machine run <id> move_to '{"x":1,"y":2,"z":3}'` | Set absolute `{x,y,z}` (`@safety`, `confirm=true`) |
| `set_heater` | `puda machine run <id> set_heater '{"celsius":40}'` | Set simulated heater (`@safety`, `confirm=false`) |
| `echo` | `puda machine run <id> echo '{"message":"hi"}'` | Round-trip a string inside a dict |
| `echo_str` / `echo_int` / `echo_float` / `echo_bool` / `echo_bytes` | `puda machine run <id> echo_int '{"value":3}'` | Round-trip JSON primitives |
| `echo_list` / `echo_dict` / `echo_any` / `echo_optional` / `echo_union` | `puda machine run <id> echo_list '{"values":[1,2]}'` | Lists, objects, any, null, unions |
| `echo_nested` / `echo_records` / `echo_mixed` / `load_layout` | `puda machine run <id> load_layout '{"layout":{"A1":"tiprack"}}'` | Nested types and `Dict[str, str]` |
| `wait` | `puda machine run <id> wait '{"seconds":5}'` | Sleep; useful for BUSY / cancel tests. Protocols should use the CLI `wait` builtin |
| `fail` | `puda machine run <id> fail '{"message":"boom"}'` | Raise so the edge returns `EXECUTION_ERROR` |
| `get_status` | `puda machine run <id> get_status` | Snapshot of homed + position + heater |
| `pause` / `resume` / `cancel` | `puda machine pause\|resume\|cancel <id>` | Immediate-command acknowledgements |
