# CLI profiles, config, and telemetry

Use `puda <command> --help` for commands and flags. These are the rules help doesn't cover.

## Profiles

- The CLI connects using the active profile only. Check `puda profile current` before changing labs; adding a profile doesn't switch to it (except the first).
- Plain profiles use `nats://` with no files. Encrypted profiles use `tls://` with both `--ca` and `--key`; gateway URLs use the same scheme. Never mix schemes. Use the lab's existing key; never generate a new one.
- `profile set key <path>` sets the field shown as `key_file`. To change encryption mode, add a separate profile.
- Removing the active profile leaves none selected.
- Before migrating an old config, back it up. Legacy top-level `nats_servers` / `gateway_servers` are ignored.
- The Python SDK doesn't read CLI profiles; edges take `ca_file` / `e2e_key_file` explicitly.

## Identity

- `user.default=true` in `puda config list` means the identity came from the OS username. Use `puda login --username <name>` to choose one.
- Don't change `user.user_id` to switch labs.

## Machine info and telemetry

- `machine info <id>` lists each telemetry stream's full `subject`; copy it into `machine watch`. An unresponsive machine exits nonzero; that is not permission to restart it.
- `machine watch` takes full subjects or `--machines`, not both. Quote wildcards (`*` one token, `>` the rest).
- Watch is live only; silence during the window doesn't prove an edge is offline. Its `--timeout` is integer seconds (`15`); `list`/`info` take durations (`3s`). Heartbeats are hidden unless requested.
- Each NDJSON line's `data` is the edge payload. Depending on the edge's SDK version, measurements are at `data.data` (with `data.timestamp`) or directly in `data`; handle both.

| Data | Subject |
| --- | --- |
| Driver stream | `puda.<id>.tlm.stream.<name>` |
| Host health | `puda.<id>.tlm.health` |
| Heartbeat | `puda.<id>.tlm.heartbeat` |
| Commands / responses | `puda.<id>.cmd.{queue,immediate}`, `puda.<id>.cmd.response.{queue,immediate}` |
| Events | `puda.<id>.evt.{log,alert,media}` |
| Updates | `puda.<id>.update`, `puda.<id>.update.response` |
