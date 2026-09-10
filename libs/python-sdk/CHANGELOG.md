# Changelog

All notable changes to the PUDA Python SDK are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

SDK versions are independent of the PUDA CLI. CLI v0.1.0 expects this SDK.

## [0.0.17] - 2026-09-09

### Breaking

- Edge driver methods must be marked `@command` or they are not advertised or callable. Drivers with no `@command` methods fail with `SDK_UPDATE_ERROR` (`Update SDK to 0.0.17`).
- Machine KV is no longer one bucket per machine. Shared `MACHINE_STATE` and `MACHINE_COMMANDS` buckets use `machine_id` as the key. Old per-machine buckets are unused.
- `MACHINE_COMMANDS` now publishes a structured `catalog` (name, signature, doc, safety) alongside the command text. A 0.0.16 edge that only wrote `{"commands": "..."}` is incompatible with current `puda machine commands` and protocol validate.
- Immediate command timeouts default to 10s (`IMMEDIATE_COMMAND_TIMEOUT`). Queue commands stay at 120s.

### Added

- `@command` decorator to allowlist remote driver methods. Inherited serial APIs and other undecorated public methods are neither advertised nor callable.
- `@safety` decorator for advisory catalog metadata (`summary`, `hazards`, `requires`, `forbidden_when`, `confirm`). It does not change dispatch. `@safety` without `@command` is ignored.
- Core NATS ping/pong on `puda.<machine_id>.cmd.ping` and broadcast `puda.cmd.ping`. Pong includes `sdk_version`, `uptime_seconds`, `run_status`, and optional `description`.
- Driver class docstring first paragraph is advertised as `description` on ping. Pass `EdgeNatsClient(..., description="...")` to override.
- Telemetry throttling: heartbeat at most every 5s, position at most every 3s.
- Shared stream and KV names in `puda.constants`, kept in sync with `infra/nats/streams/*.json`.

### Changed

- Command handling moved from `EdgeNatsClient` onto `CommandProcessor`. Transport (JetStream, response subjects, KV) stays on the NATS client.
- `run_status` on ping is derived from the in-memory execution lock (`busy` / `idle`) and is not persisted to KV.
- Command handlers must raise to fail. Returning `False` is still a successful PUDA response whose payload is `{"result": false}`.
- Immediate `reset` always clears the active `run_id` and returns success even if the driver has no `@command` `reset` method. A present `reset` handler is still invoked; a real execution error still fails.

## [0.0.16] - 2026-07-09

### Added

- `MachineState` enum for values persisted to the machine state KV store (`idle`, `busy`, `paused`, `error`, `offline`).

### Changed

- Edge state updates write a timestamped payload to the machine state KV store, including optional machine-specific fields from a registered state handler.

## [0.0.15] - 2026-04-28

First public release of the `puda` package (renamed from `puda-comms`).
