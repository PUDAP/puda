# PUDA

The Runtime Environment for Physical AI

## Overview

PUDA is a **hardware-agnostic**, **LLM-agnostic** modular platform — a **runtime for Physical AI** that lets software and AI agents plan, execute, and record operations on any physical machine, from lab instruments and robotic arms to pumps, sensors, and industrial equipment.

It is **headless by design**: there is no bundled UI. The intended way to drive PUDA is with **AI agents** (e.g. Cursor, Claude Code, Hermes Agent, OpenClaw or your own) using our [agent skills in `skills/`](skills/README.md) — ready-made playbooks for setting up projects, writing protocols, running experiments, and generating reports. When a human-facing view is useful, you can even just **build your own dashboard** on streamlit using your agent.

Skills now live alongside the CLI and SDK as ordinary repository files, not a
submodule. See the [skills migration guide](docs/skills-migration.md) for
release-pinned installation and migration from `PUDAP/skills`.

Under the hood:

- **NATS** handles all message routing between components, giving every machine and service a uniform, loosely-coupled communication layer.
- **Layered drivers and orchestration** implement the control path, cleanly separating how a device *works* from how experiments are *composed and executed*.
- **CLI** exposes the same capabilities programmatically, so agents and other clients can drive the platform through versioned commands instead of brittle, one-off scripts.
- **Env** — Each environment's machines, drivers, data, and credentials are isolated from every other, so the same skills and workflows always load the right context for wherever you are.
- **Verification** — machine runs and data collected is extracted, SHA-256 hashed and stored, giving every run verifiable provenance from command to result.

## Design Goals

PUDA is designed with three core principles:

1. **Modularity** - Distinct separation of concerns between the Driver, Communication, and Orchestration layers to ensure independent scalability, maintainability and interchangeability.
2. **AI-Native** - Every capability is exposed as a stable, programmatic interface with low-level atomic commands on machines, so autonomous agents — not just humans — are first-class operators of the platform.
3. **Scalability** - Designed to scale across many edges, from a single machine to a large fleet.

## Folder Structure

```
puda/
├── pyproject.toml      # UV workspace (Python)
├── uv.lock             # Shared lockfile for Python workspace members
├── package.json        # Nx workspace, installed with pnpm
├── apps/               # Standalone applications
│   ├── cli/            # Go CLI agents use to talk to PUDA
│   └── loadgen/        # Go load generator for NATS and fleet-scale tests
├── infra/              # Deployment for shared lab infrastructure
│   ├── chrony/         # Site NTP server; edge hosts sync to it
│   └── nats/           # NATS server topologies and JetStream resources
├── libs/               # Shared libraries
│   ├── db/             # PostgreSQL client (puda-db)
│   └── python-sdk/     # Python SDK published as the puda package
├── test-edge/          # Software-only edge for local testing
├── skills/             # Release-aligned agent skills (ordinary source files)
└── docs/               # Architecture notes
```

## Monorepo Structure

Python packages share one UV workspace. Go apps keep their own modules.

- **UV workspace** ([`pyproject.toml`](pyproject.toml)): members are `libs/*`, `services/*`, and `test-edge`. This checkout contains:
  - `libs/python-sdk` (`puda`)
  - `libs/db` (`puda-db`)
  - `test-edge`
  There is no `services/` directory yet. A package added there is picked up by the `services/*` glob.
- **Go modules**: `apps/cli` and `apps/loadgen` are not part of `uv.lock`. A small root Go module embeds the single [`compatibility.json`](compatibility.json) policy for the CLI; source builds need the full checkout. See [CLI / Python SDK compatibility](docs/compatibility.md) for advisory behavior and qualification status.
- **Nx**: task runner for the workspace, installed from `package.json` with pnpm.

Workspace packages reference each other locally:

```toml
[tool.uv.sources]
puda = { workspace = true }
```

## Development

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)
- Go 1.26+ to build `apps/cli` and `apps/loadgen`
- Docker, for the NATS and Chrony stacks under `infra/`
- Node.js and pnpm, for Nx

### Setup

From the repository root:

```bash
uv sync
```

That installs every UV workspace member into one virtual environment.

The CLI is built from `apps/cli` (`just build`). See [`apps/cli/README.md`](apps/cli/README.md). Local machine testing without hardware is in [`test-edge/README.md`](test-edge/README.md). NATS layouts are in [`infra/nats/README.md`](infra/nats/README.md).

## License

[MIT](LICENSE)
