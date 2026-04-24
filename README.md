# PUDA

Physical Unified Device Architecture - A runtime environment for Physical AI

## Overview

PUDA is a **hardware-agnostic**, **LLM-agnostic** modular platform — a **runtime for Physical AI** that lets software and AI agents plan, execute, and record operations on any physical machine, from lab instruments and robotic arms to pumps, sensors, and industrial equipment. 

It is **headless by design**: there is no bundled UI. The intended way to drive PUDA is with **AI agents** (e.g. Cursor, Claude Code, Hermes Agent, OpenClaw or your own) using our [agent skills at `pudap/skills`](https://github.com/pudap/skills) — ready-made playbooks for setting up projects, writing protocols, running experiments, and generating reports. When a human-facing view is useful, you can even just **build your own dashboard** on streamlit using your agent.

Under the hood:

- **NATS** handles all message routing between components, giving every machine and service a uniform, loosely-coupled communication layer.
- **Layered drivers and orchestration** implement the control path, cleanly separating how a device *works* from how experiments are *composed and executed*.
- **CLI** exposes the same capabilities programmatically, so agents and other clients can drive the platform through versioned commands instead of brittle, one-off scripts.
- **Env** — Each environment's machines, drivers, data, and credentials are isolated from every other, so the same skills and workflows always load the right context for wherever you are.
- **Verification** — machine runs and data collected is extracted, SHA-256 hashed and stored, giving every run verifiable provenance from command to result.

## Design Goals

PUDA is designed with two core principles:

1. **Modularity** - Distinct separation of concerns between the Driver, Communication, and Orchestration layers to ensure independent scalability, maintainability and interchangeability.
2. **AI-Native** - Every capability is exposed as a stable, programmatic interface with low-level atomic commands on machines, so autonomous agents — not just humans — are first-class operators of the platform.

## Folder Structure

This is a **monorepo** that manages multiple related packages and services in a single repository, enabling:
- Shared code and dependencies across packages
- Coordinated versioning and releases
- Easier refactoring across package boundaries
- Single lockfile for dependency management

```
puda/
├── pyproject.toml      # Root UV workspace configuration
├── uv.lock             # Shared lockfile for all Python dependencies
├── pnpm-workspace.yaml # pnpm workspace configuration
├── services/           # Application services that run independently of physical machines
│   └── logger/         # Logs command responses on NATS to PostgreSQL database
├── infra/              # Infrastructure deployment and configuration files
│   ├── nats/           # NATS messaging infrastructure setup and configuration
│   └── postgres/       # PostgreSQL database setup
├── libs/               # Shared libraries used across services and applications
│   └── comms/          # NATS-based communication library for machine-to-machine messaging
├── apps/               # Standalone applications and tools
│   └── cli/            # Golang Command-line interface for agents to interact with PUDA
└── docs/               # Documentation
```


## Monorepo Structure

PUDA uses a monorepo architecture with:

- **UV Workspace** (Python): Manages Python packages and services
  - Workspace members: `libs/*`, `services/*/*`
  - Single `uv.lock` file at the root for all Python dependencies
  - Workspace packages can depend on each other using `tool.uv.sources`

- **pnpm Workspace** (Node.js): Manages Node.js packages (if any)
  - Configured via `pnpm-workspace.yaml`

### Working with Workspace Dependencies

Workspace packages automatically reference each other. 

```toml
[tool.uv.sources]
puda-python = {workspace = true}
```

See [`docs/uv.md`](docs/uv.md) for detailed information about working with UV workspaces.

## Development

### Prerequisites

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for NATS services)
- pnpm (for Node.js packages, if needed)

### Setup

1. **Install all workspace dependencies** (from repository root):
   ```bash
   uv sync
   ```
   This installs dependencies for all workspace members and creates a shared virtual environment.