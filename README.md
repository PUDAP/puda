# PUDA

Physical Unified Device Architecture - A platform for laboratory automation and device control.

## Overview

PUDA is a modular platform that provides hardware drivers, communication infrastructure, and machine services for laboratory automation equipment. The platform uses NATS for distributed communication and supports various laboratory devices including motion systems, liquid handling equipment, and cameras.

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

## Development

### Prerequisites

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for NATS services)

### Setup

1. Install dependencies for a service:
   ```bash
   cd services/first
   uv sync
   ```

2. Run a service:
   ```bash
   uv run python first.py
   ```

3. Start NATS infrastructure:
   ```bash
   cd infra/nats
   docker compose up -d
   ```

## Project Structure

```
puda/
├── services/          # Application services
│   ├── first/        # First machine service
│   └── opentron/     # Opentrons robot services
├── infra/            # Infrastructure deployment configs
│   └── nats/         # NATS messaging infrastructure
├── libs/             # Shared libraries
│   ├── drivers/      # Hardware drivers
│   └── comms/        # Communication library
└── docs/             # Documentation
