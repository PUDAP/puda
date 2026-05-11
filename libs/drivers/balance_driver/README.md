# balance-driver

Pure Python driver for serial mass balances on the PUDA (Physical Unified Device Architecture) platform.

Connects to Arduino/ESP32 load cells and commercial balances (Mettler-Toledo, Sartorius) through the **Balance Bridge** HTTP service — a lightweight server that manages the serial connection on the host machine.

```
Python script / CLI
      │
      ▼  HTTP (localhost:9000)
Balance Bridge  (balance_bridge.py)
      │
      ▼  Serial (COM port)
Load cell / Arduino / Commercial balance
```

---

## Features

- **Read mass** — single reading, retried reading, or continuous stream
- **Tare** — zero the balance with configurable stabilisation wait
- **Calibration** — bundled 11-point 100 g load-cell CSV; supports custom CSV or manual slope/intercept
- **Diagnostics** — auto-detect baud rate, monitor raw serial data
- **`balance` CLI** — full terminal control without writing Python
- **Context manager** — automatic disconnect even on exceptions
- **Logging** — configurable file + console logging
- **Modes** — `arduino` (continuous background reader) and `commercial` (command-response)
- **NATS edge service** — connects the balance to the PUDA NATS bus for remote command and telemetry

---

## Prerequisites

Start the Balance Bridge on the host machine before using this package:

```bash
pip install pyserial fastapi uvicorn
python balance_bridge.py
# Bridge runs at http://localhost:9000
# API docs at http://localhost:9000/docs
```

---

## Installation

```bash
pip install "puda-drivers[balance]"
```

> **PUDA workspace users** — the package is already available as a workspace source.
> Run `uv sync` from the repo root and import directly; no separate install needed.

---

## Quick Start

```python
from balance_driver.machines import Balance
from balance_driver.core.logging import setup_logging
import logging, time

setup_logging(enable_file_logging=True, log_level=logging.INFO)

with Balance(port="COM8", baudrate=115200, mode="arduino") as bal:
    bal.load_default_calibration()   # push bundled 100 g CSV calibration to bridge
    time.sleep(2)                    # wait for Arduino reset + first reading

    mass = bal.get_mass(retries=3, retry_delay=1.0)
    if mass is not None:
        print(f"{mass:.6f} g  ({mass * 1000:.4f} mg)")
    else:
        print("No reading — check cable and baud rate.")
```

---

## Connection Modes

| Mode | Use when | Default baud |
|---|---|---|
| `"arduino"` | Load cell wired to Arduino / ESP32 sending continuous ADC values | 115200 |
| `"commercial"` | RS-232 command-response balance (Mettler-Toledo, Sartorius, etc.) | 9600 |

---

## Usage Examples

### Tare then Weigh

```python
from balance_driver.machines import Balance
import time

with Balance(port="COM8", baudrate=115200) as bal:
    bal.load_default_calibration()
    time.sleep(2)

    print(f"Before tare: {bal.get_mass():.6f} g")
    bal.tare(wait=5.0)          # zero with empty vessel on platform

    # place sample...
    time.sleep(1)
    print(f"Sample mass: {bal.get_mass():.6f} g")
```

### Continuous Streaming

```python
from balance_driver.machines import Balance
import time

with Balance(port="COM8") as bal:
    bal.load_default_calibration()
    time.sleep(2)

    print("Streaming — Ctrl+C to stop")
    try:
        while True:
            mass = bal.get_mass(retries=1, retry_delay=0.1)
            if mass is not None:
                print(f"\r  {mass:>12.6f} g", end="", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
```

### Commercial Balance

```python
from balance_driver.machines import Balance

with Balance(port="COM3", baudrate=9600, mode="commercial") as bal:
    print(bal.get_mass(), "g")
```

### Check Status Before Reading

```python
from balance_driver.machines import Balance
import sys, time

with Balance(port="COM8") as bal:
    bal.load_default_calibration()
    time.sleep(2)

    status = bal.status()
    if not status.get("connected"):
        sys.exit("Balance not connected")

    mass = bal.get_mass()
    print(f"{mass:.6f} g")
```

### Diagnose Unknown Baud Rate

```python
from balance_driver.machines import Balance

bal = Balance(port="COM8")
result = bal.diagnose()   # probes 9600 / 115200 / 57600 / 38400 / 19200 / 4800
print(result["summary"])
print("Best baud rate:", result["best_baudrate"])
```

---

## Calibration

The bundled `100g load cell calibration.csv` contains 11 reference points (0.05 g – 100 g).
`load_default_calibration()` reads the file locally, fits an OLS line, and pushes the result to the bridge.

| | Value |
|---|---|
| **slope** | ≈ 17 450 counts / gram |
| **intercept** | ≈ −447 counts |
| **Formula** | `grams = (raw_adc − intercept) / slope` |

```python
with Balance(port="COM8") as bal:
    # Load bundled 100 g CSV (recommended default)
    cal = bal.load_default_calibration()
    print(f"slope={cal['slope']:.4f}  intercept={cal['intercept']:.4f}")

    # Check what is currently set on the bridge
    print(bal.get_calibration())

    # Set manual slope / intercept
    bal.set_calibration(slope=17000.0, intercept=250.0)

    # Load from your own CSV file
    bal.load_calibration_from_csv(open("my_cal.csv").read())

    # Toggle raw ADC output
    bal.enable_calibration(False)   # raw ADC counts
    bal.enable_calibration(True)    # grams (default)
```

Verify calibration locally without connecting:

```python
from balance_driver.controllers.calibration import get_bundled_calibration

slope, intercept = get_bundled_calibration()
print(f"slope={slope:.4f}  intercept={intercept:.4f}")
```

### Calibrate vs Tare

| Action | What it does | When to use |
|---|---|---|
| **Calibrate** | Sets the ADC→grams conversion factor | Once per sensor, or after remounting |
| **Tare** | Zeros the current reading (removes container weight) | Before every sample measurement |

---

## `balance` CLI

After `pip install .` the `balance` command is available globally.

### Connection

```bash
balance connect    COM8                          # arduino mode, 115200 baud
balance connect    COM8 --baudrate 9600          # custom baud rate
balance connect    COM8 --mode commercial        # command-response balance
balance disconnect COM8
balance status     COM8
```

### Reading

```bash
balance read COM8                                # single reading
balance read COM8 --retries 5
balance read COM8 --continuous                   # stream until Ctrl+C
balance read COM8 --continuous --interval 0.5    # stream every 0.5 s
```

### Tare

```bash
balance tare COM8                                # tare, wait 5 s, print before/after
balance tare COM8 --wait 3.0 --tare-command z
```

### Calibration

```bash
balance calibrate COM8                           # load bundled 100 g CSV (default)
balance calibrate COM8 --get                     # show current calibration
balance calibrate COM8 --set --slope 17450.3 --intercept -446.6
balance calibrate COM8 --test --raw 1744626      # convert one ADC value → grams
balance calibrate COM8 --enable
balance calibrate COM8 --disable                 # raw ADC mode
```

### Diagnostics

```bash
balance monitor  COM8 --duration 5               # capture raw serial for 5 s
balance diagnose COM8                            # auto-detect correct baud rate
```

### Global Options

```bash
balance --bridge-host 192.168.1.10 read COM8     # bridge on another machine
balance --bridge-port 9001 status COM8
balance <command> --help                         # help for any sub-command
```

---

## Python API Reference

### `Balance` Constructor

```python
Balance(
    port        = "COM8",       # COM port — required
    baudrate    = 115200,       # serial baud rate
    mode        = "arduino",    # "arduino" or "commercial"
    bridge_host = "localhost",  # Balance Bridge hostname
    bridge_port = 9000,         # Balance Bridge HTTP port
    timeout     = 10,           # HTTP timeout seconds
)
```

### Methods

| Method | Returns | Description |
|---|---|---|
| `connect()` | `dict` | Open serial port on bridge, start background reader |
| `disconnect()` | `dict` | Close port, stop reader |
| `is_connected()` | `bool` | Check if port is open |
| `get_mass(retries, retry_delay)` | `float \| None` | Latest mass in grams |
| `get_latest()` | `dict` | Full reading dict (mass_g, fresh, age_seconds, …) |
| `read(num_readings, wait_time)` | `dict` | Blocking read (commercial mode) |
| `tare(wait, tare_command)` | `bool` | Zero the balance |
| `status()` | `dict` | Connection state + latest reading |
| `monitor(duration)` | `dict` | Capture raw serial data |
| `diagnose()` | `dict` | Test baud rates, return best |
| `load_default_calibration()` | `dict` | Push bundled 100 g CSV calibration |
| `get_calibration()` | `dict` | Get current calibration from bridge |
| `set_calibration(slope, intercept)` | `dict` | Set manual slope/intercept |
| `load_calibration_from_csv(csv_data)` | `dict` | Load calibration from CSV string |
| `enable_calibration(enabled)` | `dict` | Enable / disable ADC conversion |

---

## Logging

```python
from balance_driver.core.logging import setup_logging
import logging

setup_logging(log_level=logging.INFO)                                     # console only
setup_logging(enable_file_logging=True, logs_folder="logs")               # console + timestamped file
setup_logging(enable_file_logging=True, log_file_name="balance_run_01")   # console + named file
```

---

## NATS Edge Service

The `balance_driver/edge/` directory contains the PUDA edge service that bridges the Balance HTTP API to the NATS message bus, following the same pattern as the qubot `first` machine edge service.

### Architecture

```
NATS Server (cloud / LAN)
        │  puda.balance.commands.*  (JetStream)
        │  puda.balance.telemetry.* (core)
        ▼
  ┌──────────────────┐   HTTP REST     ┌─────────────────────┐   Serial   ┌──────────┐
  │  edge/main.py    │ ───────────────▶│  Balance Bridge     │ ──────────▶│ Balance  │
  │  (this machine)  │                 │  localhost:9000      │            │ /dev/tty │
  └──────────────────┘                 └─────────────────────┘            └──────────┘
```

### Prerequisites

The **Balance Bridge** must be running on the same machine as the edge service before starting it:

```bash
pip install pyserial fastapi uvicorn
python balance_bridge.py
# Bridge runs at http://localhost:9000
```

### Setup

```powershell
cd libs\drivers\balance_driver\edge
copy .env.example .env
notepad .env   # set BALANCE_PORT and NATS_SERVERS
```

```dotenv
MACHINE_ID=balance
BALANCE_PORT=/dev/ttyUSB0   # Windows: COM8
BAUDRATE=115200
MODE=arduino
BRIDGE_HOST=localhost
BRIDGE_PORT=9000
NATS_SERVERS=nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224
```

### Run

```powershell
# From repo root — sync the whole workspace first
uv sync

# Start the edge service
cd libs\drivers\balance_driver\edge
.\start_edge.bat
```

Or with Docker (serial port is automatically mounted from `BALANCE_PORT` in `.env`):

```bash
docker compose -f libs/drivers/balance_driver/edge/compose.yml up --build
```

### Available NATS commands

Send commands via `puda_comms.CommandService` with `machine_id="balance"`.

| Command | Key params | Description |
|---|---|---|
| `get_mass` | `retries?`, `retry_delay?` | Current mass in grams |
| `get_latest` | — | Full latest reading dict |
| `read` | `num_readings?`, `wait_time?` | Trigger a read |
| `tare` | `wait?`, `tare_command?` | Zero the balance |
| `status` | — | Connection + reader status |
| `connect` | — | Connect to balance via bridge |
| `disconnect` | — | Disconnect |
| `is_connected` | — | Reachability check |
| `set_calibration` | `slope`, `intercept?` | Set ADC→grams params |
| `get_calibration` | — | Get current calibration |
| `load_default_calibration` | — | Load built-in 100 g CSV |
| `load_calibration_from_csv` | `csv_data` | Load from CSV string |
| `enable_calibration` | `enabled` | Enable/disable conversion |

### Example

```python
import asyncio
from puda_comms import CommandService
from puda_comms.models import CommandRequest

async def run():
    async with CommandService(servers=["nats://100.109.131.12:4222"]) as svc:
        # Tare the balance
        reply = await svc.send_queue_command(
            request=CommandRequest(
                name="tare",
                machine_id="balance",
                params={"wait": 5.0},
            ),
            run_id="run-001",
            user_id="user1",
            username="Alice",
        )
        print(reply.response.status)   # SUCCESS

        # Read mass
        reply = await svc.send_queue_command(
            request=CommandRequest(
                name="get_mass",
                machine_id="balance",
                params={"retries": 3},
            ),
            run_id="run-001",
            user_id="user1",
            username="Alice",
        )
        print(reply.response)   # SUCCESS + mass_g

asyncio.run(run())
```

### Telemetry

Every telemetry tick the edge publishes:

| Subject | Payload |
|---|---|
| `puda.balance.telemetry.heartbeat` | Heartbeat timestamp |
| `puda.balance.telemetry.health` | `{"connected": true, "mass_g": 12.345, "port": "/dev/ttyUSB0"}` |
| `puda.balance.telemetry.state` | `{"connected": true, "mass_g": 12.345, "port": "...", "mode": "arduino"}` |

### Edge file structure

```
balance_driver/edge/
├── main.py          # entry point — Config, BalanceEdgeDriver, EdgeRunner wiring
├── pyproject.toml   # balance-edge package (puda-comms + puda-drivers as workspace sources)
├── .env.example     # configuration template
├── .env             # your local values (git-ignored)
├── Dockerfile       # build from repo root
├── compose.yml      # docker compose — mounts serial device
└── start_edge.bat   # Windows one-click start
```

---

## AI Skills (Cursor / Codex)

| File | Purpose |
|---|---|
| [`skills/balance/SKILL.md`](skills/balance/SKILL.md) | Machine capabilities, selection workflow, output guidance |
| [`skills/balance/references/balance-machine.md`](skills/balance/references/balance-machine.md) | All methods, sequencing rules, run patterns, Python + CLI templates |
| [`skills/balance/references/calibration.md`](skills/balance/references/calibration.md) | ADC→grams formula, bundled CSV data, calibration vs tare guidance |

---

## Requirements

| Dependency | Required for |
|---|---|
| Python >= 3.10 | All |
| `requests >= 2.31` | HTTP calls to Balance Bridge |
| `pyserial >= 3.5` | Balance Bridge serial layer (`[balance]` extra) |
| `fastapi >= 0.100` | Balance Bridge server (`[balance]` extra) |
| `uvicorn >= 0.23` | Balance Bridge server (`[balance]` extra) |

---

## Development

```bash
# Install all dependencies including dev extras
uv sync

# Run balance driver tests only
uv run pytest tests/test_balance_reading.py tests/test_balance_calibration.py tests/test_balance_cli.py -v

# Run all tests
uv run pytest tests/ -v
```

---

## Package Structure

```
balance_driver/
├── __init__.py                        # Balance, BalanceBridgeClient, setup_logging
├── core/
│   ├── http_client.py                 # BalanceBridgeClient — HTTP verbs to bridge
│   └── logging.py                     # setup_logging() — file + console
├── controllers/
│   ├── reading.py                     # connect, disconnect, read, tare, status, monitor, diagnose
│   ├── calibration.py                 # set/get/load calibration, bundled CSV OLS fit
│   └── 100g load cell calibration.csv # 11-point calibration (0.05 g – 100 g)
├── machines/
│   └── balance.py                     # Balance — unified high-level interface
├── cli.py                             # balance CLI entry-point
└── edge/                              # NATS edge service (Balance ↔ PUDA message bus)
    ├── main.py                        # BalanceEdgeDriver + EdgeRunner wiring
    ├── pyproject.toml                 # balance-edge package (workspace sources)
    ├── .env.example                   # configuration template
    ├── Dockerfile                     # container build (context: repo root)
    ├── compose.yml                    # docker compose — mounts serial device
    └── start_edge.bat                 # Windows quick-start

examples/
├── get_balance_reading.py             # single reading with CLI args
├── tare_balance.py                    # tare + before/after reading
└── diagnose_balance.py               # auto-detect baud rate

skills/balance/
├── SKILL.md
└── references/
    ├── balance-machine.md
    └── calibration.md

tests/
├── test_balance_reading.py            # reading controller tests (17 tests)
├── test_balance_calibration.py        # calibration controller + CSV tests (23 tests)
└── test_balance_cli.py                # CLI entry-point tests (17 tests)
```

---

## License

MIT License — see [LICENSE](LICENSE) file for details.
