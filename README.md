# PUDA

Physical Unified Device Architecture - A platform for laboratory automation and device control.

## Overview

PUDA is a modular platform that provides hardware drivers, communication infrastructure, and machine services for laboratory automation equipment. The platform uses NATS for distributed communication and supports various laboratory devices including motion systems, liquid handling equipment, and cameras.

This is a **monorepo** that manages multiple related packages and services in a single repository, enabling:
- Shared code and dependencies across packages
- Coordinated versioning and releases
- Easier refactoring across package boundaries
- Single lockfile for dependency management

## Services

Services are standalone applications that run on machines and handle device control and communication.

### `services/first/`

Service for the "first" machine. Integrates motion control, deck management, liquid handling, and camera capabilities.

- **Language**: Python
- **Dependencies**: `puda-drivers`, `puda-comms`
- **Features**:
  - NATS-based command queue and immediate command handling
  - Execution state management with cancellation support
  - Telemetry publishing (position, health, heartbeat)
  - Hardware initialization and lifecycle management

### `services/opentron/`

Services for Opentrons robot integration.

- **`edge/`**: Edge service for Opentrons robots
  - NATS client implementation
  - Robot control and status reporting
- **`mcp/`**: MCP (Model Context Protocol) server for Opentrons integration

## Infrastructure

Infrastructure deployment and configuration files.

### `infra/nats/`

NATS messaging infrastructure setup and configuration.

- **Components**:
  - Docker Compose configuration for NATS cluster
  - Kubernetes manifests for high-availability deployment
  - Stream configuration scripts
  - NATS configuration files

## Libraries

Shared libraries used across services and applications.

### `libs/drivers/`

Hardware drivers for laboratory automation equipment.

- **Package**: `puda-drivers`
- **Features**:
  - **Motion Control**: G-code compatible motion systems (e.g., QuBot)
  - **Liquid Handling**: Sartorius rLINE® pipettes and dispensers
  - **Camera Control**: Webcam and USB camera support
  - **Labware Management**: Standard labware definitions and deck layout management
  - **Serial Communication**: Robust serial port management with automatic reconnection
  - **Logging**: Configurable logging with optional file output

- **Key Components**:
  - `machines/`: Machine classes (e.g., `First`)
  - `move/`: Motion control and deck management
  - `transfer/liquid/`: Liquid handling controllers
  - `cv/`: Computer vision and camera interfaces
  - `labware/`: Labware definitions and management
  - `core/`: Core utilities (position, serial controller, logging)

### `libs/comms/`

NATS-based communication library for machine-to-machine messaging.

- **Package**: `puda-comms`
- **Features**:
  - `MachineClient`: NATS client for machines with JetStream support
  - `ExecutionState`: Execution state management with cancellation support
  - Subject pattern: `puda.{machine_id}.{category}.{sub_category}`
  - Support for queue commands, immediate commands, telemetry, and events

- **Key Components**:
  - `machine_client.py`: NATS client implementation
  - `execution_state.py`: Execution state and cancellation management

## Monorepo Structure

PUDA uses a monorepo architecture with:

- **UV Workspace** (Python): Manages Python packages and services
  - Workspace members: `libs/*` and `services/*/*`
  - Single `uv.lock` file at the root for all Python dependencies
  - Workspace packages can depend on each other using `tool.uv.sources`

- **pnpm Workspace** (Node.js): Manages Node.js packages (if any)
  - Configured via `pnpm-workspace.yaml`

### Working with Workspace Dependencies

Workspace packages automatically reference each other. For example, `services/first/edge` depends on `puda-drivers` and `puda-comms`:

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
   uv run --package first-edge python services/first/edge/main.py
   
   # Or navigate to the service directory
   cd services/first/edge
   uv run python main.py
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

## Project Structure

```
puda/
├── pyproject.toml     # Root UV workspace configuration
├── uv.lock           # Shared lockfile for all Python dependencies
├── pnpm-workspace.yaml # pnpm workspace configuration
├── services/          # Application services (workspace members)
│   ├── first/         # First machine service
│   │   ├── edge/      # Edge service (workspace member)
│   │   └── mcp/       # MCP server (workspace member)
│   └── opentron/      # Opentrons robot services
│       ├── edge/      # Edge service (workspace member)
│       └── mcp/       # MCP server (workspace member)
├── infra/             # Infrastructure deployment configs
│   ├── nats/          # NATS messaging infrastructure
│   └── postgres/      # PostgreSQL database setup
├── libs/               # Shared libraries (workspace members)
│   ├── drivers/       # Hardware drivers (puda-drivers)
│   └── comms/          # Communication library (puda-comms)
└── docs/               # Documentation
```
