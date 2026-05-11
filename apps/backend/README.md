# Backend

A LangGraph based backend to orchestrate distributed MCP servers for lab machines.

## Development

### Prerequisites

- Python >= 3.14.2
- [uv](https://docs.astral.sh/uv/) package manager

### Running Locally

From the repository root, install dependencies:

```bash
uv sync
```

Then run the FastAPI application with auto-reload:

```bash
cd apps/backend
uv run uvicorn app.main:app --reload --host localhost --port 8000
```

The API will be available at `http://localhost:8000` and will automatically reload when you make code changes.

### API Documentation

Once running, you can access:
- Interactive API docs: `http://localhost:8000/docs`
- Alternative API docs: `http://localhost:8000/redoc`

## Production

### Building the Docker Image

From the repository root:

```bash
cd apps/backend
docker compose build
```

### Pushing to GitHub Container Registry

1. **Authenticate with GitHub Container Registry:**

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

Or use a GitHub Personal Access Token with `write:packages` permission.

2. **Build and push the image:**

The `compose.yml` file is already configured with the image name `ghcr.io/pudap/backend:latest`. Simply build and push:

```bash
cd apps/backend
docker compose build
docker compose push
```

This will build the image and push it to `ghcr.io/pudap/backend:latest`.

### Running in Production

```bash
cd apps/backend
docker compose up -d
```

The service will be available at `http://localhost:8000` (or the port specified in your `.env` file via `BACKEND_PORT`).

