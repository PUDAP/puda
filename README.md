# PUDA

Physical Unified Device Architecture - A runtime environment for Physical AI

## Overview

PUDA is a **hardware-agnostic**, **LLM-agnostic** modular platform. The same infrastructure fits any system or machine you can drive with commands while reading responses back to close the loop—state, positions, measurements, or other telemetry. NATS is used for message routing; layered drivers and orchestration implement the control path; and the CLI exposes stable programmatic interfaces for agents and other clients, instead of brittle one-off scripts.

This is a **monorepo** that manages multiple related packages and services in a single repository, enabling:
- Shared code and dependencies across packages
- Coordinated versioning and releases
- Easier refactoring across package boundaries
- Single lockfile for dependency management

## Design Goals

PUDA is designed with two core principles:

1. **Modularity** - Distinct separation of concerns between the Driver, Communication, and Orchestration layers to ensure independent scalability, maintainability and interchangeability.
2. **AI-Native** - Prioritize programmatic access and low level commands to support autonomous agents

## Folder Structure

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
puda-comms = {workspace = true}
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