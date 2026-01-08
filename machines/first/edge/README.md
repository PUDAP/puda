# First Edge Service

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

