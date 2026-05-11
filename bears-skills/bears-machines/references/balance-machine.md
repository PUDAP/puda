---
name: balance-machine
description: Arduino-based USB mass balance driver for Linux. Reads calibrated mass from a load-cell via serial and publishes telemetry to NATS. Use for gravimetric feedback in liquid handling experiments.
---

# Balance Machine

Arduino-based USB mass balance connected via Linux USB serial (`/dev/ttyUSB0` or `/dev/ttyACM0`).  


## What It Does

- Reads raw ADC values from an Arduino over USB serial and converts them to grams using a linear calibration model fitted from a load-cell CSV.
- Runs an edge service that connects to NATS and publishes calibrated mass readings as telemetry.
- Background reader thread streams readings continuously; latest value is available at any time via `get_mass()`.

---

## Setup

### Prerequisites

- Python 3.11+ and `uv`
- Arduino balance connected at `/dev/ttyUSB3` or `/dev/ttyACM3`

### Environment

```bash
cp edge/.env.example edge/.env
```

Edit `edge/.env`:

| Variable | Description |
|---|---|
| `MACHINE_ID` | Unique ID for this balance instance |
| `SERIAL_PORT` | e.g. `/dev/ttyUSB1` |
| `BAUDRATE` | Must match Arduino sketch (typically `115200`) |
| `NATS_SERVERS` | NATS server URL |

### Start Edge Service

```bash
uv sync --all-packages
uv run --package balance-edge python edge/balance.py
```

The service retries automatically on fatal errors (5 s backoff) and ignores `KeyboardInterrupt` to stay running in unattended environments.

---

## Calibration

- Default calibration CSV: `driver/src/balance_driver/controller/100g load cell calibration.csv`
- A custom CSV can be supplied via `Balance(calibration_csv="path/to/file.csv")`
- Calibration uses a linear model: `mass_g = slope * raw_adc + intercept`

---

## Rules

1. Always call `startup()` before reading and `shutdown()` after — do not skip.
2. Always tare (`driver.tare(wait=2.0)`) immediately after every successful balance connection/startup.
3. Always check `fresh == True` before using `get_mass()` values; stale data (`age > 5 s`) indicates a disconnection.
4. Serial port is Linux-only (`/dev/ttyUSB*` or `/dev/ttyACM*`). Ask the user for the correct port — do not assume.
5. Ask user if unsure — **do not assume**.
