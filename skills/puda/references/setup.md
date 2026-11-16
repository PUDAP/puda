# PUDA setup

## Setup puda

1. **Install CLI**: Ensure `puda` is installed and on your PATH so it can be invoked globally. If missing, download the binary for your platform from the [Puda releases page](https://github.com/PUDAP/puda/releases), install it, and add it to PATH.
2. **Ensure dependencies**: Ensure `python3`, `pip`, and `npx` are available; install them first if missing.
3. **Login**: Ask the user for their username if not already known — do not assume. Log in with `puda login -u <username>`.
4. **Select a NATS profile**: Inspect `puda profile list` and `puda profile current`. Use an existing intended profile with `puda profile switch <name>`. For a new profile, get the name and broker URLs from the user or deployment configuration; do not assume the lab. Plaintext: `puda profile add <name> --servers <nats-urls>`. Encrypted: `puda profile add <name> --servers <tls-urls> --ca <local-ca-path> --key <local-key-path>`. Both files are required for an encrypted CLI profile. The first profile is activated automatically if none is selected; otherwise explicitly switch to the intended profile.
5. **Install skills**: Run `puda skills install` to install agent skills for puda.

## Setup project

Run `puda init` (e.g. `puda init .` or `puda init <folder_name>`).

Only after puda is set up and the project is initialized, proceed with protocol generation, machine commands, or experiment workflows.

## Project Folder Structure

```text
.
├── project.md                        # project context and legacy history
├── protocols/                        # generated protocol files (puda-protocol skill)
├── puda.config                       # puda config file
└── puda.db                           # puda database file
```

## Updating puda skills

To refresh or update puda skills:

```bash
puda skills update
```
