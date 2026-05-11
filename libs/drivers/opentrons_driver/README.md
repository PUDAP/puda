# opentrons_driver

Pure Python driver for the [Opentrons OT-2](https://opentrons.com/ot-2/) liquid-handling robot on the PUDA (Physical Unified Device Architecture) platform.

Communicates directly with the OT-2 REST API over HTTP — no Opentrons App, no MCP server, no Docker required.

---

## Features

- **Robot control** — upload and run Opentrons protocols directly from Python
- **Run management** — play, pause, stop, and monitor protocol runs
- **Labware management** — upload custom labware definitions to the robot
- **Protocol builder** — construct OT-2 protocols programmatically using Pydantic models
- **Logging** — configurable file + console logging
- **NATS edge service** — connects the OT-2 to the PUDA NATS bus for remote command and telemetry
- **Cross-platform** — works on Windows, macOS, and Linux

---

## Installation

```bash
pip install puda-drivers
```

> **PUDA workspace users** — the package is already available as a workspace source.
> Run `uv sync` from the repo root and import directly; no separate install needed.

---

## Quick Start

```python
from opentrons_driver.machines import OT2
from opentrons_driver.core.logging import setup_logging
import logging

setup_logging(enable_file_logging=True, log_level=logging.INFO)

robot = OT2(robot_ip="192.168.50.64")

if not robot.is_connected():
    raise RuntimeError("Robot is unreachable")

result = robot.upload_and_run(open("my_protocol.py").read())
print(result["run_status"])   # "succeeded" / "failed" / "stopped"
```

---

## Building a Protocol Programmatically

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

---

## Run Control

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

---

## Custom Labware

Custom labware definitions live as JSON files in `labware/`.
Drop a new `.json` file there and it is auto-discovered at import time — no Python edits required.

```python
from opentrons_driver.controllers.resources import BUILTIN_LABWARE, MASS_BALANCE_VIAL_30ML

robot = OT2("192.168.50.64")

# Upload a built-in definition by convenience alias
robot.upload_labware(MASS_BALANCE_VIAL_30ML)

# Upload any built-in definition by load_name
robot.upload_labware(BUILTIN_LABWARE["mass_balance_vial_50000"])

# Upload from an arbitrary JSON file on disk
robot.upload_labware("/path/to/my_labware.json")
```

To add a new labware, create a JSON file in `labware/` following the
[Opentrons labware schema](https://github.com/Opentrons/opentrons/tree/edge/shared-data/labware).
The file must include `parameters.loadName`; that value becomes its key in `BUILTIN_LABWARE`
and is appended to `get_labware_types()` automatically.

---

## Logging

```python
from opentrons_driver.core.logging import setup_logging
import logging

setup_logging(log_level=logging.INFO)                                    # console only
setup_logging(enable_file_logging=True, logs_folder="logs")              # console + timestamped file
setup_logging(enable_file_logging=True, log_file_name="run_2026_03_30")  # console + named file
```

---

## NATS Edge Service

The `edge/` directory contains the PUDA edge service that bridges the OT-2 HTTP API to the NATS message bus, following the same pattern as the qubot `first` machine.

The `OT2` machine driver is passed **directly** to `EdgeRunner` — no adapter layer.  
`EdgeRunner` dispatches incoming NATS commands by matching `command.name` to `OT2` method names and calling them with `**command.params`.

### Architecture

```
NATS Server (cloud / LAN)
        │  puda.{machine_id}.cmd.queue       (JetStream)
        │  puda.{machine_id}.cmd.response.*  (JetStream)
        │  puda.{machine_id}.tlm.*           (core NATS)
        ▼
  ┌──────────────────┐   HTTP REST   ┌─────────────────┐
  │  edge/main.py    │ ─────────────▶│  OT-2 Robot     │
  │  EdgeRunner(OT2) │               │  :31950          │
  └──────────────────┘               └─────────────────┘
```

### Setup

```powershell
cd libs\drivers\opentrons_driver\edge
copy .env.example .env
notepad .env
```

```dotenv
MACHINE_ID=ot2
ROBOT_IP=192.168.50.64
ROBOT_PORT=31950
NATS_SERVERS=nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224
```

### Run

```powershell
# From repo root
uv sync

cd libs\drivers\opentrons_driver\edge
.\start_edge.bat
```

Or with Docker (build context is repo root):

```bash
docker compose -f libs/drivers/opentrons_driver/edge/compose.yml up --build
```

### Available NATS commands

Send commands via `puda_comms.CommandService` with `machine_id="ot2"`.  
Command names map directly to `OT2` method names.

| Command | Key params | Description |
|---|---|---|
| `upload_and_run` | `code` (str), `filename?`, `wait?`, `max_wait?`, `poll_interval?` | Upload and run a protocol |
| `get_status` | `run_id?` (str) | Get run status (latest if omitted) |
| `pause` | `run_id` (str) | Pause a running protocol |
| `resume` | `run_id` (str) | Resume a paused protocol |
| `stop` | `run_id` (str) | Stop / cancel a run |
| `upload_labware` | `labware` (dict) | Upload a custom labware definition |
| `is_connected` | — | Check robot reachability |
| `get_labware_types` | — | List known labware load-names |
| `get_pipette_types` | — | List known pipette instrument names |

### Example

```python
import asyncio
from puda_comms import CommandService
from puda_comms.models import CommandRequest

async def run():
    async with CommandService(servers=["nats://100.109.131.12:4222"]) as svc:
        reply = await svc.send_queue_commands(
            requests=[
                CommandRequest(
                    name="upload_and_run",
                    machine_id="ot2",
                    params={
                        "code": open("my_protocol.py").read(),
                        "wait": True,
                        "max_wait": 300,
                    },
                    step_number=1,
                )
            ],
            run_id="run-001",
            user_id="user1",
            username="Alice",
            timeout=360,
        )
        print(reply.response.status)   # SUCCESS / ERROR

asyncio.run(run())
```

### Telemetry

Every telemetry tick the edge publishes:

| Subject | Payload |
|---|---|
| `puda.ot2.telemetry.heartbeat` | Heartbeat timestamp |
| `puda.ot2.telemetry.health` | `{"connected": true, "robot_ip": "192.168.50.64"}` |
| `puda.ot2.telemetry.state` | `{"robot_ip": "192.168.50.64"}` |

### Edge file structure

```
edge/
├── main.py          # entry point — Config, EdgeRunner(OT2) wiring
├── pyproject.toml   # ot2-edge package (puda-comms + puda-drivers as workspace sources)
├── .env.example     # configuration template
├── .env             # your local values (git-ignored)
├── Dockerfile       # build from repo root
├── compose.yml      # docker compose — no devices needed (network robot)
└── start_edge.bat   # Windows one-click start
```

---

## API Reference

### `OT2` Constructor

```python
OT2(
    robot_ip = "192.168.50.64",  # OT-2 IP address — required
    port     = 31950,             # HTTP port
    timeout  = 10,                # request timeout (seconds)
)
```

### Methods

| Method | Returns | Description |
|---|---|---|
| `is_connected()` | `bool` | Ping `GET /health` |
| `upload_and_run(code, filename, wait, max_wait, poll_interval)` | `dict` | Upload protocol and start run |
| `get_status(run_id)` | `dict` | Status of a run (latest if `run_id` is `None`) |
| `pause(run_id)` | `bool` | Pause a running protocol |
| `resume(run_id)` | `bool` | Resume a paused protocol |
| `stop(run_id)` | `bool` | Stop / cancel a run |
| `upload_labware(labware)` | `dict` | Upload a custom labware definition |
| `get_labware_types()` | `list[str]` | Known labware load-names |
| `get_pipette_types()` | `list[str]` | Known pipette instrument names |

---

## Package Structure

```
opentrons_driver/
├── __init__.py                        # OT2, Protocol, ProtocolCommand, setup_logging
├── core/
│   ├── http_client.py                 # OT2HttpClient — base URL, headers, HTTP verbs
│   └── logging.py                     # setup_logging() — file + console
├── controllers/
│   ├── protocol.py                    # Protocol + ProtocolCommand, to_python_code(), upload_protocol()
│   ├── run.py                         # create/play/pause/stop run, wait_for_completion()
│   └── resources.py                   # LABWARE_TYPES, PIPETTE_TYPES, upload_custom_labware(),
│                                      # BUILTIN_LABWARE, MASS_BALANCE_VIAL_30/50ML
├── labware/                           # Custom labware definitions (one JSON file per labware)
│   ├── mass_balance_vial_30000.json   # AMDM 30 mL vial on mass balance
│   └── mass_balance_vial_50000.json   # AMDM 50 mL vial on mass balance
├── machines/
│   └── ot2.py                         # OT2 — unified high-level interface
└── edge/                              # NATS edge service (OT-2 ↔ PUDA message bus)
    ├── main.py                        # Config + EdgeRunner(OT2) wiring
    ├── pyproject.toml                 # ot2-edge package (workspace sources)
    ├── .env.example                   # configuration template
    ├── Dockerfile                     # container build (context: repo root)
    ├── compose.yml                    # docker compose
    └── start_edge.bat                 # Windows quick-start
```

---

## Requirements

| Dependency | Required for |
|---|---|
| Python >= 3.10 | All |
| `requests >= 2.31` | OT-2 HTTP communication |
| `pydantic >= 2.0` | Protocol model |

---

## Cursor / Codex Skills

An AI skill is provided in [`skills/opentrons-ot2/`](../skills/opentrons-ot2/) following the same structure as the [PUDAP/skills puda-machines skill](https://github.com/PUDAP/skills/tree/main/puda-machines).

| File | Purpose |
|---|---|
| `SKILL.md` | Machine capabilities, selection workflow, output guidance |
| `references/ot2-machine.md` | All commands + params, sequencing rules, run management, full protocol template |
| `references/labware.md` | Labware definitions, pipette types, deck slot layout |

The skill enforces mandatory sequencing:
`load_labware` → `load_instrument` → `pick_up_tip` → liquid ops → `drop_tip`
(protocol always ends tip-free).
