# puda-drivers

Pure Python hardware drivers for the PUDA (Physical Unified Device Architecture) platform.

| Driver | Hardware | Transport |
|---|---|---|
| [`opentrons_driver`](#opentrons-ot-2-driver) | [Opentrons OT-2](https://opentrons.com/ot-2/) liquid-handling robot | HTTP REST `:31950` |
| [`balance_driver`](#mass-balance-driver) | Arduino / ESP32 load cells and commercial balances | Serial via Balance Bridge HTTP `:9000` |

Each driver ships with its own **NATS edge service** (`edge/`) that connects the hardware to the PUDA message bus.

---

## Package Structure

```
libs/drivers/
├── opentrons_driver/                  # OT-2 robot driver
│   ├── __init__.py
│   ├── core/
│   │   ├── http_client.py             # OT2HttpClient — base URL, headers, HTTP verbs
│   │   └── logging.py                 # setup_logging() — file + console
│   ├── controllers/
│   │   ├── protocol.py                # Protocol + ProtocolCommand, to_python_code(), upload_protocol()
│   │   ├── run.py                     # create/play/pause/stop run, wait_for_completion()
│   │   └── resources.py               # LABWARE_TYPES, PIPETTE_TYPES, BUILTIN_LABWARE
│   ├── labware/                       # Custom labware JSON definitions
│   │   ├── mass_balance_vial_30000.json
│   │   └── mass_balance_vial_50000.json
│   ├── machines/
│   │   └── ot2.py                     # OT2 — unified high-level interface
│   └── edge/                          # NATS edge service (OT-2 ↔ PUDA bus)
│       ├── main.py
│       ├── pyproject.toml
│       ├── .env.example
│       ├── Dockerfile
│       ├── compose.yml
│       └── start_edge.bat
├── balance_driver/                    # Mass balance driver
│   ├── __init__.py
│   ├── core/
│   │   ├── http_client.py             # BalanceBridgeClient — HTTP verbs to bridge
│   │   └── logging.py                 # setup_logging() — file + console
│   ├── controllers/
│   │   ├── reading.py                 # connect, disconnect, read, tare, status, monitor, diagnose
│   │   ├── calibration.py             # set/get/load calibration, bundled CSV OLS fit
│   │   └── 100g load cell calibration.csv
│   ├── machines/
│   │   └── balance.py                 # Balance — unified high-level interface
│   ├── cli.py                         # balance CLI entry-point
│   └── edge/                          # NATS edge service (Balance ↔ PUDA bus)
│       ├── main.py
│       ├── pyproject.toml
│       ├── .env.example
│       ├── Dockerfile
│       ├── compose.yml
│       └── start_edge.bat
├── tests/
│   ├── conftest.py
│   ├── test_protocol.py
│   ├── test_run.py
│   ├── test_labware.py
│   ├── test_balance_reading.py
│   ├── test_balance_calibration.py
│   └── test_balance_cli.py
├── pyproject.toml                     # puda-drivers package
└── README.md
```

---

## Installation

```bash
# OT-2 driver only
pip install puda-drivers

# OT-2 + balance driver
pip install "puda-drivers[balance]"
```

> **PUDA workspace users** — both drivers are already available as workspace sources.
> Run `uv sync` from the repo root; no separate install needed.

---

## Opentrons OT-2 Driver

### Features

- Upload and run Opentrons protocols directly from Python
- Play, pause, stop, and monitor protocol runs
- Upload custom labware definitions
- Build protocols programmatically with Pydantic models
- NATS edge service for remote command and telemetry

### Quick Start

```python
from opentrons_driver.machines import OT2
from opentrons_driver.core.logging import setup_logging
import logging

setup_logging(log_level=logging.INFO)

robot = OT2(robot_ip="192.168.50.64")

if not robot.is_connected():
    raise RuntimeError("Robot is unreachable")

result = robot.upload_and_run(open("my_protocol.py").read())
print(result["run_status"])   # "succeeded" / "failed" / "stopped"
```

### Build a Protocol Programmatically

```python
from opentrons_driver.controllers.protocol import Protocol, ProtocolCommand
from opentrons_driver.machines import OT2

robot = OT2(robot_ip="192.168.50.64")

protocol = Protocol(
    protocol_name="Simple Transfer",
    author="Lab",
    description="Transfer 100 µL from well A1 to B1",
    robot_type="OT-2",
    api_level="2.23",
    commands=[
        ProtocolCommand(command_type="load_labware", params={
            "name": "tiprack", "labware_type": "opentrons_96_tiprack_300ul", "location": "1"
        }),
        ProtocolCommand(command_type="load_labware", params={
            "name": "plate", "labware_type": "corning_96_wellplate_360ul_flat", "location": "2"
        }),
        ProtocolCommand(command_type="load_instrument", params={
            "name": "p300", "instrument_type": "p300_single_gen2",
            "mount": "right", "tip_racks": ["tiprack"]
        }),
        ProtocolCommand(command_type="transfer", params={
            "pipette": "p300", "volume": 100,
            "source_labware": "plate", "source_well": "A1",
            "dest_labware": "plate", "dest_well": "B1",
        }),
    ],
)

result = robot.upload_and_run(protocol.to_python_code())
print(result["run_status"])
```

### Run Control

```python
robot = OT2("192.168.50.64")

result = robot.upload_and_run(code, wait=False)
run_id = result["run_id"]

robot.pause(run_id)
robot.resume(run_id)
robot.stop(run_id)

status = robot.get_status(run_id)
print(status["run_status"])
```

### Custom Labware

```python
from opentrons_driver.controllers.resources import BUILTIN_LABWARE, MASS_BALANCE_VIAL_30ML

robot = OT2("192.168.50.64")
robot.upload_labware(MASS_BALANCE_VIAL_30ML)
robot.upload_labware(BUILTIN_LABWARE["mass_balance_vial_50000"])
robot.upload_labware("/path/to/my_labware.json")
```

### OT-2 NATS Edge Service

Bridges the OT-2 HTTP API to the PUDA NATS bus. Run on any machine that can reach the robot over the network.

```
NATS Server
      │  puda.ot2.commands.*  (JetStream)
      │  puda.ot2.telemetry.* (core)
      ▼
edge/main.py  ── HTTP REST ──▶  OT-2 :31950
```

**Setup and run:**

```powershell
cd libs\drivers\opentrons_driver\edge
copy .env.example .env   # set ROBOT_IP and NATS_SERVERS
uv sync                  # from repo root
.\start_edge.bat
```

**Available NATS commands** (`machine_id="ot2"`):

| Command | Key params | Description |
|---|---|---|
| `run_protocol` | `code`, `filename?`, `wait?`, `max_wait?` | Upload and run a protocol |
| `get_status` | `run_id?` | Get run status |
| `pause` | `run_id` | Pause a running protocol |
| `resume` | `run_id` | Resume a paused protocol |
| `stop` | `run_id` | Stop / cancel a run |
| `upload_labware` | `labware` (dict) | Upload a custom labware definition |
| `is_connected` | — | Check robot reachability |

> See [`opentrons_driver/README.md`](opentrons_driver/README.md) for the full edge reference, Docker setup, and AI skills.

---

## Mass Balance Driver

### Features

- Single reading, retried reading, or continuous stream
- Tare with configurable stabilisation wait
- Bundled 11-point 100 g load-cell calibration CSV; supports custom CSV or manual slope/intercept
- Auto-detect baud rate, monitor raw serial data
- `balance` CLI for full terminal control
- Context manager — automatic disconnect on exceptions
- Modes: `arduino` (continuous background reader) and `commercial` (command-response)
- NATS edge service for remote command and telemetry

### Prerequisites

The Balance Bridge must be running before using this driver:

```bash
pip install pyserial fastapi uvicorn
python balance_bridge.py
# Bridge at http://localhost:9000
```

### Quick Start

```python
from balance_driver.machines import Balance
from balance_driver.core.logging import setup_logging
import logging, time

setup_logging(log_level=logging.INFO)

with Balance(port="COM8", baudrate=115200, mode="arduino") as bal:
    bal.load_default_calibration()
    time.sleep(2)   # wait for first reading

    mass = bal.get_mass(retries=3, retry_delay=1.0)
    print(f"{mass:.6f} g  ({mass * 1000:.4f} mg)")
```

### Tare then Weigh

```python
from balance_driver.machines import Balance
import time

with Balance(port="COM8") as bal:
    bal.load_default_calibration()
    time.sleep(2)

    print(f"Before tare: {bal.get_mass():.6f} g")
    bal.tare(wait=5.0)

    time.sleep(1)
    print(f"Sample mass: {bal.get_mass():.6f} g")
```

### `balance` CLI

```bash
balance connect    COM8
balance read       COM8 --continuous
balance tare       COM8
balance calibrate  COM8                          # load bundled 100 g CSV
balance calibrate  COM8 --set --slope 17450 --intercept -447
balance diagnose   COM8                          # auto-detect baud rate
balance status     COM8
balance disconnect COM8
```

### Balance NATS Edge Service

Bridges the Balance HTTP Bridge to the PUDA NATS bus. Requires the Balance Bridge to be running on the same machine.

```
NATS Server
      │  puda.balance.commands.*  (JetStream)
      │  puda.balance.telemetry.* (core)
      ▼
edge/main.py  ── HTTP ──▶  Balance Bridge :9000  ── Serial ──▶  Balance
```

**Setup and run:**

```powershell
cd libs\drivers\balance_driver\edge
copy .env.example .env   # set BALANCE_PORT and NATS_SERVERS
uv sync                  # from repo root
.\start_edge.bat
```

**Available NATS commands** (`machine_id="balance"`):

| Command | Key params | Description |
|---|---|---|
| `get_mass` | `retries?`, `retry_delay?` | Current mass in grams |
| `get_latest` | — | Full latest reading dict |
| `read` | `num_readings?`, `wait_time?` | Trigger a read |
| `tare` | `wait?`, `tare_command?` | Zero the balance |
| `status` | — | Connection + reader status |
| `connect` / `disconnect` | — | Manage serial connection |
| `set_calibration` | `slope`, `intercept?` | Set ADC→grams params |
| `get_calibration` | — | Get current calibration |
| `load_default_calibration` | — | Load built-in 100 g CSV |
| `enable_calibration` | `enabled` | Enable/disable conversion |

> See [`balance_driver/README.md`](balance_driver/README.md) for the full edge reference, Docker setup, and AI skills.

---

## Logging

Both drivers share the same `setup_logging()` interface:

```python
from opentrons_driver.core.logging import setup_logging   # or balance_driver.core.logging
import logging

setup_logging(log_level=logging.INFO)                                    # console only
setup_logging(enable_file_logging=True, logs_folder="logs")              # + timestamped file
setup_logging(enable_file_logging=True, log_file_name="run_2026_03_30")  # + named file
```

---

## Requirements

| Dependency | Required for |
|---|---|
| Python >= 3.10 | All |
| `requests >= 2.31` | OT-2 HTTP communication |
| `pydantic >= 2.0` | Protocol model |
| `pyserial >= 3.5` | Balance Bridge serial layer (`[balance]` extra) |
| `fastapi >= 0.100` | Balance Bridge server (`[balance]` extra) |
| `uvicorn >= 0.23` | Balance Bridge server (`[balance]` extra) |

---

## Development

```bash
# Install all dependencies including dev extras
uv sync

# Run all tests
uv run pytest tests/ -v

# Run OT-2 tests only
uv run pytest tests/test_protocol.py tests/test_run.py tests/test_labware.py -v

# Run balance tests only
uv run pytest tests/test_balance_reading.py tests/test_balance_calibration.py tests/test_balance_cli.py -v

# Run with coverage
uv run pytest tests/ --cov=opentrons_driver --cov=balance_driver --cov-report=html
```

---

## License

MIT License — see [LICENSE](LICENSE) file for details.
