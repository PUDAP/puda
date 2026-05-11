---
name: bears-machines
description: Discover PUDA machine capabilities at bears and choose the right machines for protocol generation. Use when you need to know more about a machine, how to use a machine, or how to generate commands and protocols for any PUDA-connected machine.
---

# BEARS machines

## Goal

Provide machine-selection and capability guidance for PUDA workflows, then load the correct machine reference before generating commands.

## Critical Rule

If you are unsure which machine should be used for a command, **ask the user** before proceeding.  
Do **not** assume.

## Machine Capabilities and When to Use

### First Machine (`machine_id: "first"`)

Use for **liquid handling and deck operations**.

Capabilities:
- Pipetting workflows: aspirate, dispense, attach tip, drop tip
- Deck and labware workflows: load deck, position-dependent operations
- Sequenced robotic handling steps in wet-lab protocols

Use this machine when:
- The task is about moving liquids between wells/labware
- The user mentions tip usage, aspiration/dispensing, or deck slots/labware setup

Before command generation:
- Refer to: [first-machine](references/first-machine.md)
- Run `puda machine commands first` to understand available commands
- Follow constraints and sequencing in `references/first-machine.md`

### Biologic Machine (`machine_id: "biologic"`)

Use for **electrochemical testing and characterization**.

Capabilities:
- OCV (Open Circuit Voltage)
- CA (Chronoamperometry)
- PEIS / GEIS (Impedance spectroscopy)
- CV (Cyclic Voltammetry)
- MPP variants (MPP, MPP_Cycles, MPP_Tracking)

Use this machine when:
- The task is an electrochemical measurement or battery/cell characterization
- The user asks for OCV, CA, EIS, CV, or MPP tests

Before command generation:
- Refer to: [biologic-machine](references/biologic-machine.md)
- Run `puda machine commands biologic` to understand available commands
- Follow constraints in `references/biologic-machine.md`

### Balance Machine

Use for **gravimetric mass measurement via an Arduino-based USB load-cell balance on Linux**.

Capabilities:
- Continuous calibrated mass readings from a load-cell over USB serial (`/dev/ttyUSB*` or `/dev/ttyACM*`)
- Background reader thread streaming readings at ~4 Hz; no polling required
- Tare command to zero the balance before a dispense step
- Freshness check (`fresh` flag) to detect stale/disconnected readings
- NATS telemetry publishing via the edge service
- Custom calibration CSV support

Use this machine when:
- The workflow requires weighing a container before or after a liquid transfer
- The user asks for gravimetric calibration, transfer error calculation, or balance feedback
- The task involves viscosity or transfer accuracy experiments needing mass data

Before use:
- Refer to: [balance-machine](references/balance-machine.md)
- Ask the user for the **Linux serial port** (`/dev/ttyUSB1`, etc.) — do not assume
- Ensure the edge service is running (`uv run --package balance-edge python edge/balance.py`)

### Opentrons Machine (`machine_id: "opentrons"`)

Use for **automated liquid handling and full protocol generation on the Opentrons OT-2 robot**.

Capabilities:
- Full protocol code generation via `Protocol.to_python_code()` — produces valid runnable OT-2 Python
- Pipetting workflows: `aspirate`, `dispense`, `transfer` (with auto-chunking for large volumes)
- Tip management: `pick_up_tip`, `drop_tip`
- Deck and labware setup: `load_labware`, `load_instrument`
- Flow control: `flow_rate`, `air_gap`, `blow_out`, `touch_tip`, `move_to`
- Protocol utilities: `delay`, `comment`, `home`
- CSV-driven loops: `read_csv_file` + `loop` for data-driven protocols
- Custom labware support: AMDM mass balance vials (30 mL, 50 mL) loaded inline
- All gen2 pipette types: p10, p20, p300, p1000 (single and multi-channel)
- **External camera image capture**: `camera_capture` — triggers the external camera mounted above the deck to capture and save a still image of the wellplate

Use this machine when:
- The user references an Opentrons OT-2 robot
- The task involves generating a complete OT-2 protocol or individual liquid handling commands
- The user mentions Opentrons labware (tip racks, well plates, reservoirs, NEST, Corning, mass balance vials)
- The workflow requires data-driven dispensing from a CSV file
- The workflow requires capturing a camera image of the wellplate after dispensing steps

Before command generation:
- Refer to: [opentrons-machine](references/opentrons-machine.md)
- Run `puda machine commands opentrons` to understand available commands
- Follow all command types, params, sequencing rules, and labware constraints in `references/opentrons-machine.md`


## Selection Workflow

1. Parse user intent and identify the tasks.
2. Match intent to the machine capabilities above.
3. If machine selection is unclear or ambiguous, **ask the user** and wait for confirmation.
4. Load the corresponding reference file and CLI help.
5. Generate commands only after machine choice is confirmed.

## Output Guidance

When answering machine-selection questions:
- State the recommended machine and a one-line reason tied to capability.
- If uncertain, ask a direct clarification question instead of guessing.

## Critical sequencing rules
- `opentrons` protocols must always end with no tip attached to any pipette.
- `opentrons` deck slot (`location`) for every `load_labware` command must be explicitly confirmed by the user — **never assume a slot**.
- `opentrons` `capture_image` must be its own standalone protocol — never combined with pipetting commands in the same protocol.
- `balance` — always call `startup()` before reading and `shutdown()` after. Always tare before a dispense step. Always verify `fresh == True` before using a reading.

