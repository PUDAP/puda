# CLI profiles, config, and telemetry

Check installed command help for the exact interface. CLI and Python SDK versions are independent.

## Profiles and migration

Before upgrading an older config, preserve a private backup and record the intended broker URLs and security paths. The user config is normally `~/.config/puda/config.json` on Linux, `~/Library/Application Support/puda/config.json` on macOS, or `%APPDATA%\puda\config.json` on Windows. Do not expose passwords or key contents. Legacy top-level `nats_servers` and `gateway_servers` do not provide a fallback; the CLI requires an active profile.

Use `puda profile --help` for commands. Check `puda profile current` before changing the selected lab, and use the actual lab addresses. Login is not required; the CLI creates a default identity when none exists.

- The first profile activates if none is selected. Adding another does not switch to it. `profile current` verifies selection.
- Encrypted CLI profiles require both `--ca` and `--key`, and all URLs must use `tls://`. Plain profiles use `nats://` with neither file. Never mix schemes. File paths refer to the CLI host; profiles store paths, not key contents. Obtain the existing lab key, do not generate an unrelated replacement.
- `profile add --gateway-servers <urls>` sets optional remote cluster URLs; their scheme must match the main servers.
- `profile set <field> <value>` edits the active profile, not its selection. Fields: `nats_servers`, `gateway_servers`, `ca`, `key`. The output field is `key_file`, but the setter is `key`. `ca` and `key` can only be changed on an already encrypted profile. Use a separate profile to change encryption mode.
- `profile remove <name>` removes a profile. Removing the active one leaves none selected; it does not choose another automatically.
- Profile output is JSON by default; `--human` gives text. No active profile is an error from `profile current`, not proof the broker is offline.
- CLI connection settings come from the active profile, not project settings or old security environment variables. The Python SDK is separate: its client takes explicit `ca_file` / `e2e_key_file` arguments and does not load CLI profiles or security environment variables.

## User config versus project config

`config get` accepts `user.user_id`, `user.username`, and `user.default`; `config set` accepts only `user.user_id` and `user.username` (setting `user.username` replaces a default identity). `config list` prints three `key=value` lines (`user.user_id`, `user.username`, `user.default`), not JSON. `user.default=true` means the identity was derived from the OS username; run `puda login --username <name>` to choose one. Do not change the user's ID merely to change the selected lab. `config edit` opens the user config in an editor. Use `puda project config --help` for project settings.

## Discover streams before watching

`list` broadcasts on `puda.cmd.ping` and reports responsive edges, descriptions, `livestream_count`, and `tlm_stream_count`. It is not a persisted inventory. `info` sends direct requests on `puda.<machine_id>.cmd.ping`; machine IDs may be comma-separated or separate arguments.

Info's JSON `results` array includes each machine's `status`, SDK version, run status, available network/description information, `livestreams`, and `tlm_streams`. Each telemetry stream advertises `name`, `subject`, interval in seconds, and optional description. Copy that full subject into watch. An unresponsive machine has an error result and causes a nonzero exit status; do not interpret absence as authorization to restart it. `info` is not a substitute for `machine state` or `machine commands` when those details are needed.

## Watch subjects

Subjects are positional arguments, not machine IDs or short names such as `pos`. Subject arguments and `--machines` / `-m` are mutually exclusive. Without subjects, machine IDs expand to `puda.<id>.>`; with neither subjects nor IDs, the subscription is `puda.*.>`.

Quote wildcard subjects. `*` matches one token; `>` matches remaining tokens and must be last. Watch uses live Core NATS subscriptions, not replay of stored telemetry. Silence may mean no samples were published during the window; it does not by itself prove the edge is offline.

| Data | Full subject |
| --- | --- |
| Driver stream | `puda.<id>.tlm.stream.<name>` |
| Host health | `puda.<id>.tlm.health` |
| Heartbeat | `puda.<id>.tlm.heartbeat` |
| Commands | `puda.<id>.cmd.queue`, `puda.<id>.cmd.immediate` |
| Responses | `puda.<id>.cmd.response.queue`, `puda.<id>.cmd.response.immediate` |
| Events | `puda.<id>.evt.log`, `puda.<id>.evt.alert`, `puda.<id>.evt.media` |
| Updates | `puda.<id>.update`, `puda.<id>.update.response` |

Watch emits NDJSON with `timestamp` (CLI receipt time), `subject`, `machine_id`, `category`, `topic`, and `data` (the decrypted edge payload, unchanged); e.g. a position stream has topic `stream.pos`. Health and stream telemetry may be wrapped as `{timestamp, data: {...}}` (measurements at `data.data`, edge publication time at `data.timestamp`) or have measurement fields directly in `data` beside `timestamp`, depending on the edge's `sdk_version`; accept both shapes. The selected encrypted profile handles decryption. `--human` gives text instead. Heartbeats are hidden unless `--include-heartbeat` is set or a supplied subject explicitly names `tlm.heartbeat`. Watch `--timeout` takes integer seconds (e.g. `15`), whereas info/list take durations (e.g. `3s`). `--timeout 0` runs until interrupted.
