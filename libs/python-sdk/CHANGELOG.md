# Changelog

All notable changes to the PUDA Python SDK are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

SDK versions are independent of the PUDA CLI. CLI v0.1.3 expects this SDK.

## [Unreleased]

- Optional `EdgeNatsClient(ca_file=..., e2e_key_file=...)` arguments with
  explicit configuration and independent TLS/payload encryption settings.
  Edge clients do not automatically read security paths from the environment.
- Edge encryption keys are isolated per client, including commands, updates,
  telemetry, KV state, and key rotation. Invalid configured files fail early.

These changes retain the Git source version 0.0.19; the existing PyPI 0.0.19
artifacts predate them and cannot be replaced.

## [0.0.19] - 2026-10-14

### Added

- Optional AES-256-GCM payload encryption, shared with the CLI. It stays off unless `PUDA_E2E_KEY_FILE` points at a lab key. `tls://` brokers also need `PUDA_NATS_CA`.
- `seal` and `open_payload` for that frame.
- Edges adopt lab-key rotations from the shared keyring and republish machine state after the key changes.
- Pong includes `e2e_encrypt_kid`, `e2e_decrypt_kids`, and `e2e_persist` when encryption is on.
- `cryptography` is a dependency, used only when a lab key is set.

### Changed

- Publishes, machine state, the command catalog, and ping/pong are sealed when a lab key is configured.

## [0.0.18] - 2026-09-30

### Breaking

- `puda.<machine_id>.tlm.pos` is removed. Position is a telemetry stream on `puda.<machine_id>.tlm.stream.pos`; declare it on the driver with `@tlm_stream(interval=..., name="pos")`.

### Added

- `@tlm_stream(interval=..., name=...)` decorator. `EdgeRunner` polls each marked driver method at its own interval and publishes non-`None` results to `puda.<machine_id>.tlm.stream.<name>`.
- `EdgeNatsClient.declare_tlm_stream`, `publish_tlm_stream`, and `publish_tlm_stream_threadsafe` for streams published outside the decorator.
- Pong replies include `tlm_streams` (name, subject, interval, description) for `puda machine info`.
- `@machine_state` decorator. The marked driver method's dict is merged into every `MACHINE_STATE` update. An explicit `state_handler` still takes precedence.

### Changed

- `EdgeRunner` publishes the heartbeat itself, and `telemetry_handler` is now optional. Existing `publish_heartbeat()` calls are harmless, because heartbeats are throttled to one every 5s.
- `EdgeRunner` publishes host health (`cpu`, `mem`, `temp`) on `tlm.health` every 5s. `psutil` is now an SDK dependency. Pass `host_health=False` if the edge publishes its own health.

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
