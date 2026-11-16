# CLI 0.1.x profiles, config, and telemetry

Target: CLI 0.1.3. Check installed command help if a different version is in use. CLI and Python SDK versions are independent.

## Profiles and migration

Before upgrading an older config, preserve a private backup and record the intended broker URLs and security paths. The user config is normally `~/.config/puda/config.json` on Linux, `~/Library/Application Support/puda/config.json` on macOS, or `%APPDATA%\puda\config.json` on Windows. Do not expose passwords or key contents. Legacy top-level `nats_servers` and `gateway_servers` do not provide a fallback; the CLI requires an active profile.

Inspect before changing the selected lab:

```bash
puda profile list
puda profile current
```

If no user config exists, log in with the user's supplied username first: `puda login -u <username>`. Choose one connection mode using the actual lab addresses:

```bash
# Plaintext example
puda profile add lab --servers nats://nats.example:4222
puda profile switch lab

# TLS + E2EE example (alternative connection)
puda profile add secure-lab --servers tls://nats.example:4222 --ca /absolute/path/ca.pem --key /absolute/path/e2e.key
puda profile switch secure-lab
```

- The first profile activates if none is selected. Adding another does not switch to it. `profile current` verifies selection.
- Encrypted CLI profiles require both `--ca` and `--key`, and all URLs must use `tls://`. Plain profiles use `nats://` with neither file. Never mix schemes. File paths refer to the CLI host; profiles store paths, not key contents. Obtain the existing lab key, do not generate an unrelated replacement.
- `profile add --gateway-servers <urls>` sets optional remote cluster URLs; their scheme must match the main servers.
- `profile set <field> <value>` edits the active profile, not its selection. Fields: `nats_servers`, `gateway_servers`, `ca`, `key`. The output field is `key_file`, but the setter is `key`. `ca` and `key` can only be changed on an already encrypted profile. Use a separate profile to change encryption mode.
- `profile remove <name>` removes a profile. Removing the active one leaves none selected; it does not choose another automatically.
- Profile output is JSON by default; `--human` gives text. No active profile is an error from `profile current`, not proof the broker is offline.
- CLI connection settings come from the active profile, not project settings or old security environment variables. The Python SDK is separate: SDK 0.0.21 requires explicit client `ca_file` / `e2e_key_file` arguments; it does not load CLI profiles or security environment variables automatically.

## User config versus project config

```bash
puda config list
puda config get user.username
puda config get user.user_id
puda config set user.username <username>
```

Only `user.user_id` and `user.username` are accepted by `config get/set`; `config list` prints those values as `key=value`, not JSON. Do not change the user's ID merely to change the selected lab. `config edit` opens the user config in an editor. Use `puda project config --help` for project settings.

Replace `puda config get nats_servers` with `puda profile current`, and `puda config set nats_servers <urls>` with `puda profile set nats_servers <urls>` after selecting a profile. The equivalent gateway setter is `puda profile set gateway_servers <urls>`.

## Discover streams before watching

```bash
puda machine list --timeout 3s
puda machine info first,balance --timeout 3s
puda machine info first --human
```

`list` broadcasts on `puda.cmd.ping` and reports responsive edges, descriptions, `livestream_count`, and `tlm_stream_count`. It is not a persisted inventory. `info` sends direct requests on `puda.<machine_id>.cmd.ping`; machine IDs may be comma-separated or separate arguments.

Info's JSON `results` array includes each machine's `status`, SDK version, run status, available network/description information, `livestreams`, and `tlm_streams`. Each telemetry stream advertises `name`, `subject`, interval in seconds, and optional description. Copy that full subject into watch. An unresponsive machine has an error result and causes a nonzero exit status; do not interpret absence as authorization to restart it. `info` is not a substitute for `machine state` or `machine commands` when those details are needed.

## Watch subjects

```bash
puda machine watch puda.first.tlm.stream.pos --timeout 15
puda machine watch puda.first.tlm.stream.pos puda.balance.tlm.stream.weight --timeout 15
puda machine watch 'puda.*.tlm.stream.>' --timeout 15
puda machine watch --machines first,balance --timeout 15
puda machine watch 'puda.*.tlm.heartbeat' --timeout 15
```

The first two examples assume info actually advertises those streams. Subjects are positional arguments, not machine IDs or short names such as `pos`. Subject arguments and `--machines` / `-m` are mutually exclusive. Without subjects, machine IDs expand to `puda.<id>.>`; with neither subjects nor IDs, the subscription is `puda.*.>`.

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

Watch emits NDJSON with `timestamp`, `subject`, `machine_id`, `category`, `topic`, and `data`; e.g. a position stream has topic `stream.pos`. The selected encrypted profile handles decryption. `--human` gives text instead. Heartbeats are hidden unless `--include-heartbeat` is set or a supplied subject explicitly names `tlm.heartbeat`. Watch `--timeout` takes integer seconds (e.g. `15`), whereas info/list take durations (e.g. `3s`). `--timeout 0` runs until interrupted.
