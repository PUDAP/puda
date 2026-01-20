# First Edge Service

- Meant to be ran on the machine or a server connected to the machine
- Provides connection to NATS and handles tranlation of nats commands to machine methods for execution

## User Guide

### Setup

1. Copy the environment configuration file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and configure the following variables:
   - `MACHINE_ID`: Machine identifier (default: `first`)
   - `NATS_SERVERS`: Comma-separated list of NATS server URLs (default: `nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224`)
   - `QUBOT_PORT`: Serial port for the QuBot gantry controller (default: `/dev/ttyACM0`)
   - `SARTORIUS_PORT`: Serial port for the Sartorius pipette controller (default: `/dev/ttyUSB0`)
   - `CAMERA_INDEX`: Camera device index or path (default: `0`)

3. Run the service using one of the following methods:

   **Option A: Baremetal (using uv)**
   ```bash
   uv sync --all-packages
   uv run first.py
   ```

   **Option B: Docker Compose**
   ```bash
   docker compose pull && docker compose up -d
   ```

## Dependencies

For the most updated code (development), use editable path dependencies in `pyproject.toml`:

```toml
dependencies = [
    "puda-drivers",
    "puda-comms",
]

[tool.uv.sources]
puda-drivers = { path = "../../libs/drivers", editable = true }
puda-comms = { path = "../../libs/comms", editable = true }
```

If not using editable dependencies, use versioned dependencies instead:

```toml
dependencies = [
    "puda-drivers>=0.0.12",
    "puda-comms>=0.1.0",
]
```

## Docker Deployment

### Prerequisites

- Docker and Docker Compose installed
- USB devices available: `/dev/ttyACM0` and `/dev/ttyUSB0`
- Camera device available: `/dev/video0`
- Build context: The Dockerfile expects the workspace root structure (requires building from workspace root or updating Dockerfile COPY paths)

### Running with Docker Compose

1. Build and start the service:
   ```bash
   cd machines/first/edge
   docker compose up -d --build
   ```

2. View logs:
   ```bash
   docker compose logs -f
   ```

3. Stop the service:
   ```bash
   docker compose down
   ```

### Build Context

The `compose.yml` uses build context `../..` (workspace root) to access both the service code and the shared libraries (`libs/drivers` and `libs/comms`). This allows the Dockerfile to copy all necessary files in a single build context.

### Device Access

The service requires access to:
- Serial devices: `/dev/ttyACM0` (qubot) and `/dev/ttyUSB0` (sartorius)
- Camera: `/dev/video0`

If devices are not accessible, you may need to:
- Add your user to the `dialout` group for serial devices: `sudo usermod -aG dialout $USER`
- Ensure camera permissions are set correctly
- Or use `privileged: true` in `compose.yml` (less secure)

### Development Mode

To enable live code reloading, uncomment the volume mounts in `compose.yml`:

```yaml
volumes:
  - ../../libs:/app/libs:ro
  - ./first.py:/app/machines/first/edge/first.py:ro
```

### Building and Pushing to GitHub Container Registry

1. **Login to GitHub Container Registry:**
   ```bash
   echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
   ```
   Or use a GitHub Personal Access Token with `write:packages` permission.

2. **Build the image:**
   ```bash
   cd machines/first/edge
   docker compose build
   ```

3. **Tag and push the image:**
   ```bash
   # Push to GitHub Container Registry
   docker push ghcr.io/PUDAP/first-edge:latest
   ```

   Or use docker compose to build and push:
   ```bash
   docker compose build
   docker compose push
   ```

4. **Pull and use the image:**
   ```bash
   docker pull ghcr.io/PUDAP/first-edge:latest
   docker compose up -d
   ```

### Docker Image Details

- **Base Image**: Python 3.14-slim
- **Package Manager**: uv (Astral)
- **Image Name**: `ghcr.io/pudap/first-edge:latest`
- **Build Context**: Workspace root (`../..` from `machines/first/edge/`)
- **Working Directory**: `/app/machines/first/edge`

