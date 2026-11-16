---
name: puda-edge
description: Build and update PUDA Python edge drivers using a machine SDK/API or desktop GUI. Use for driver.py, main.py, command and safety decorators, telemetry, or puda machine update.
---

# PUDA Python edges

Build thin Python hardware wrappers that connect to NATS and advertise typed, documented commands. Name the repository `puda-<machine_id>-edge`.

## Select the task

- **SDK/API driver, configuration, telemetry, or multi-machine host:** read [driver contract and scaffolding](references/driver.md). Scaffold from [edge-python-template](https://github.com/PUDAP/edge-python-template). See [Integrating a New Machine](https://docs.puda.co/docs/0.1.0/setup/integrating-a-new-machine) and [ViPSA](https://github.com/PUDAP/ViPSA) for shared workspaces.
- **Instrument controlled through desktop software:** read [GUI edge workflows](references/gui-edge.md). Use [edge-python-gui-template](https://github.com/PUDAP/edge-python-gui-template) and the [Opentrons worked example](https://github.com/PUDAP/opentrons-gui-edge). A vendor manual or screenshots with task instructions provide workflow context; supplement with live captures when available. Also read the driver contract when changing shared lifecycle/configuration code.
- **Add or change `@safety`:** read [safety metadata](references/safety.md) for the exact five-field contract and example.
- **Remote update:** inspect `puda machine update --help` for targeting and options, then use `puda machine update` as appropriate.

## Essential contract

- Inspect the chosen template's dependencies and SDK contract. Keep Python commands atomic, typed, JSON-compatible, and documented with units, defaults, prerequisites, returned evidence, and errors.
- Only `@command` methods are remote commands. A driver without them fails startup. Put a one-sentence machine description in the Driver class docstring for discovery.
- Raise on failure with targets and hardware response; returning `False` is a successful PUDA response. Preserve template lifecycle and cleanup.
- For GUI edges, expose only `capture_screenshot` as a low-level remote command; implement high-level workflows using inherited helpers internally.
- Keep identity, NATS, and connection settings configurable. Use placeholder `.env.example` values; do not copy another machine's credentials.
- `@safety` publishes advisory metadata and does not block edge dispatch. Use `confirm=True` for motion, chemical mixing, heat, pressure, or other irreversible hardware actions; read the safety reference before implementing it.
- Verify commands offline before desktop/hardware validation, then inspect `puda machine commands <machine_id>`. Distinguish implementation, fixture tests, desktop observations, and hardware evidence.

Use **puda-deployment** for host/NATS/hardware commissioning and **puda** for CLI setup.
