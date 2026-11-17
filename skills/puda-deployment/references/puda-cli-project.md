# PUDA CLI, project, and skills SOP

1. Verify `puda --version` and compare with the required edge library/protocol version (CLI and SDK versions are independent).
2. Install from an official release and verify a published checksum when available.
3. Login is optional: without it the CLI uses a default identity from the OS username. To record a specific name, run `puda login --username <name>` with the name the user supplies; GitHub identity is separate. Verify with `puda config list` (`user.default=true` means the OS-derived default).
4. Inspect `puda profile list` / `puda profile current` and select the intended lab with `puda profile switch <name>`. Create a missing profile with `puda profile add <name> --servers <urls>`; encrypted CLI profiles require `tls://` URLs plus both `--ca <local-path>` and `--key <local-path>`. Plain profiles use `nats://` without either file. Edit an active profile with `puda profile set nats_servers <urls>`. `puda config` now manages only user identity, not broker settings.
5. Install/update skills using documented PUDA commands.
6. Initialize (`puda init [path] --name <name>`) or locate a project. `puda init` creates `project.md`, `puda.config`, and `puda.db`; the agent creates `protocols/` when protocols are generated.
7. Run project-dependent protocol commands from the project root.
8. Before authoring, use `puda machine list`, `puda machine info <id>`, `puda machine state`, and `puda machine commands <id>`. Info advertises `tlm_streams` with full subjects. Verify an advertised stream with `puda machine watch <full-subject> --timeout 15`; use `--machines <ids>` instead for all topics from selected machines, never together with subject arguments. Quote wildcard subjects. Watch emits NDJSON and hides heartbeats unless explicitly requested.

Machine discovery can be stale. Record returned timestamps and compare with current UTC.
