# PUDA Monorepo Architecture Diagram

This document provides a visual overview of how all components in the PUDA monorepo connect to each other.

## Interactive Diagram

View the interactive diagram on Excalidraw:
[PUDA Architecture Diagram](https://excalidraw.com/#json=T66aPX4xIKqhM9RdHKj4l,TXFJfO5AdOquBanq4Ach_A)

## Component Overview

### Frontend
- **Cursor**: IDE that uses the PUDA CLI
- **SKILLS.md**: Documentation for agent capabilities
- **puda-cli**: command line for agents to use the PUDA platform

### PUDA CLI (Go Application)
- **MCP Client**: Connects to servers to provide simulation capabilities
- **NATS connection**: Connects to NATS cluster for messaging
- **Project config**: Manages puda project configuration
- **DB client**: Database client for persistent storage

### NATS Cluster
- **nats1, nats2, nats3**: High-availability NATS server cluster
- Acts as the central message bus for all communication
- Handles:
  - Commands (queue and immediate)
  - Responses (queue and immediate)
  - Telemetry (fire-and-forget)
  - Events (fire-and-forget)
  - Machine state (KV store)

### Machines
- **Machine controller**: Hardware control logic (First, Biologic)
- **NATS edge client**: Connects machines to NATS cluster
- **Dockerized**: All machines run in containers
- **Types**: First machine (liquid handling), Biologic (electrochemical)

### Logger Service
- Subscribes to NATS response streams
- Logs all command responses to PostgreSQL
- Provides durable message consumption

### PostgreSQL
- **Database**: Persistent storage for logs and state
- **Object Storage**: Integration with MinIO or ReductStore for media files

### Backend (LangGraph)
- **Orchestrates**: Coordinates distributed MCP servers
- **MCP protocol**: Communicates with MCP servers via NATS
- Manages agent workflows and task execution

## Data Flow

1. **Frontend → PUDA CLI**: Frontend uses CLI for machine control
2. **PUDA CLI → NATS**: CLI publishes commands and subscribes to responses
3. **NATS → Machines**: Commands are delivered to machines via NATS streams
4. **Machines → NATS**: Machines publish responses, telemetry, and events
5. **NATS → Logger Service**: Logger subscribes to response topics
6. **Logger Service → PostgreSQL**: Responses are persisted to database
7. **Backend → NATS**: Backend orchestrates MCP servers via NATS

## Libraries

- **puda-comms**: NATS client (EdgeNatsClient, CommandService)
- **puda-db**: Database utilities

## Infrastructure

- **NATS**: Message bus with JetStream (commands, responses, telemetry)
- **PostgreSQL**: Centralized persistant storage for logs and state
- **Docker**: Containerized machines and services

## Related Documentation

- [NATS Architecture](./nats_architecture_diagram.md) - Detailed NATS messaging patterns
- [Backend README](../apps/backend/README.md) - Backend service details
- [Logger Service README](../services/logger/README.md) - Logger service details