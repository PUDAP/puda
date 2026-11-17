# Python edge driver

## Scaffold

1. Create the repo from the template. Resolve every `TODO`.
2. Set a unique lowercase hyphenated `MACHINE_ID` in `.env` with `NATS_SERVERS`.
3. Implement `driver.py`, then wire config and the driver into `main.py`.
4. Keep helpers private (`_name`). Only `@command` methods are advertised.

Verify with `puda machine commands <machine_id>` after the edge is connected.

Several instruments on one PC can share one uv workspace; each subdirectory gets its own `MACHINE_ID`, `driver.py`, and `main.py`. See the docs and [PUDAP/ViPSA](https://github.com/PUDAP/ViPSA).

## Driver

`driver.py` is a thin wrapper around the hardware API. Method names, docstrings, parameters, and return annotations are the command interface agents see. Put a one-sentence summary on the **Driver class docstring**; `EdgeRunner` advertises the first paragraph on `puda machine list` and `puda machine info` so agents do not need `puda machine commands` just to learn what the machine is.

- Decorate every remotely callable method with `@command`. Undecorated public methods are not advertised or callable over NATS. A driver with no `@command` methods fails at startup.
- Keep commands atomic: one hardware action per method.
- Parameters must be primitives (`str`, `int`, `float`, `bool`) or simple lists/dicts of primitives.
- Document args, returns, and raised errors in every public docstring; they provide context for agents.
- Raise on failure with the command, targets, and hardware response. Returning `False` is still a successful PUDA response (`{"result": false}`).
- `shutdown`, `home`, and `reset` are optional. `shutdown` runs before the edge stops. `home` is triggered by `puda machine home`. `puda machine reset` always clears the active `run_id`, then calls `reset` if present.

```python
from puda import command, safety

class Driver:
    """Software-only PUDA test machine. Commands are simulated in memory; no hardware is required."""

    @command
    def shutdown(self) -> bool:
        """Release hardware resources. If defined, called before the edge stops."""
        ...

    @command
    def home(self) -> bool:
        """Home the machine. If defined, triggered by `puda machine home <machine_id>`."""
        ...

    @command
    def reset(self) -> bool:
        """Software reset. Optional. `puda machine reset` clears the run first, then calls this if present."""
        ...

    @command
    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        """
        Move the machine head to an absolute position.

        Args:
            x_mm: Target X position in millimeters.
            y_mm: Target Y position in millimeters.
            z_mm: Target Z position in millimeters.

        Raises:
            RuntimeError: If the hardware rejects the move.
        """
        result = self._hardware.move_to(x_mm=x_mm, y_mm=y_mm, z_mm=z_mm)
        if not result.ok:
            raise RuntimeError(
                "Failed to move machine head "
                f"to x={x_mm}, y={y_mm}, z={z_mm}: {result.error}"
            )
        return True
```

## Configure

Keep `MACHINE_ID` and `NATS_SERVERS` in `.env`. Add typed hardware fields to `Config` in `main.py` so missing values fail at startup. Pass those fields into `Driver(...)`.

Telemetry must be JSON-serializable. Pass plain dictionaries; the SDK may wrap health and named-stream payloads (including position) as `{timestamp, data: {...}}`, so consumers must accept both wrapped and flat shapes. Publish heartbeat plus whatever position, health, and state the machine actually has. Field names should match the hardware (joints, plunger, focus), not a cartesian template.
