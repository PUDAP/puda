# PUDA setup

## Setup puda

1. **Install CLI**: Ensure `puda` is installed and on your PATH so it can be invoked globally. If missing, download the binary for your platform from the [Puda releases page](https://github.com/PUDAP/puda/releases), install it, and add it to PATH.
2. **Ensure dependencies**: Ensure `python3`, `pip`, and `npx` are available; install them first if missing.
3. **Identity (optional)**: Login is not required; without it the CLI uses a default identity from the OS username (`puda config list` shows `user.default=true`). If the user wants a specific username, run `puda login -u <username>` with the name they supply — do not invent one.
4. **Select a NATS profile**: Inspect `puda profile list` and `puda profile current`. Use an existing intended profile with `puda profile switch <name>`. For a new profile, get the name and broker URLs from the user or deployment configuration; do not assume the lab. Plaintext: `puda profile add <name> --servers <nats-urls>`. Encrypted: `puda profile add <name> --servers <tls-urls> --ca <local-ca-path> --key <local-key-path>`. Both files are required for an encrypted CLI profile. The first profile is activated automatically if none is selected; otherwise explicitly switch to the intended profile.
5. **Install skills**: Run `puda skills install` to install agent skills for puda. If the deployment monorepo has a `skills/` folder, run `puda skills install <path-to-monorepo>/skills` instead; it installs the PUDA skills and symlinks the deployment's own skills, so edits stay tracked in Git.

## Setup project

Run `puda init [path] --name <project_name>` (e.g. `puda init . --name "<project_name>"` or `puda init <folder_name> --name "<project_name>" --description "<description>"`). `--name` is required; `--description` is optional; the path defaults to the current directory. Get the project name from the user. This creates `project.md`, `puda.config`, and `puda.db`; `protocols/` is created when protocols are generated.

Set up puda and initialize the project before protocol execution or experiments.

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
