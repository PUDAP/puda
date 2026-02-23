# PUDA

Physical Unified Device Architecture - A platform for laboratory automation and device control.

## Overview

PUDA is a modular platform that provides hardware drivers, communication infrastructure, and machine services for laboratory automation and orchestration. The platform uses NATS for distributed communication and supports various laboratory hardware.

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
├── machines/           # Edge services that run on minipcs connected to the machines
│   ├── first/          # First machine service
│   ├── biologic/       # Biologic machine service
│   └── opentron/       # Opentrons machine service
├── services/           # Application services that run independently of physical machines
│   └── logger/         # Logs command responses on NATS to PostgreSQL database
├── infra/              # Infrastructure deployment and configuration files
│   ├── nats/           # NATS messaging infrastructure setup and configuration
│   └── postgres/       # PostgreSQL database setup
├── libs/               # Shared libraries used across services and applications
│   ├── drivers/        # Hardware drivers for laboratory automation equipment
│   └── comms/          # NATS-based communication library for machine-to-machine messaging
├── apps/               # Standalone applications and tools
│   ├── cli/            # Golang Command-line interface for agents to interact with PUDA
│   └── backend/        # LangGraph-based backend for orchestration (not in use because there are better agents out there)
└── docs/               # Documentation
```


## Monorepo Structure

PUDA uses a monorepo architecture with:

- **UV Workspace** (Python): Manages Python packages and services
  - Workspace members: `libs/*`, `services/*/*`, and `machines/*/*`
  - Single `uv.lock` file at the root for all Python dependencies
  - Workspace packages can depend on each other using `tool.uv.sources`

- **pnpm Workspace** (Node.js): Manages Node.js packages (if any)
  - Configured via `pnpm-workspace.yaml`

### Working with Workspace Dependencies

Workspace packages automatically reference each other. For example, `machines/first/edge` depends on `puda-drivers` and `puda-comms`:

```toml
[tool.uv.sources]
puda-drivers = {workspace = true}
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

2. **Run a service**:
   ```bash
   # From repository root
   uv run --package first-edge python machines/first/edge/first.py
   
   # Or navigate to the service directory
   cd machines/first/edge
   uv run python first.py
   ```

3. **Add a dependency to a workspace package**:
   ```bash
   # From the package directory
   cd libs/drivers
   uv add some-package
   
   # Or from root
   uv add --package puda-drivers some-package
   ```

4. **Start NATS infrastructure**:
   ```bash
   cd infra/nats
   docker compose up -d
   ```

