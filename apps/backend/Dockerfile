FROM python:3.14-slim-bookworm

WORKDIR /app

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install uv for Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace files needed for uv workspace
COPY pyproject.toml uv.lock ./
COPY apps/backend/ ./apps/backend/

# Install dependencies using uv
WORKDIR /app/apps/backend
RUN uv sync --frozen --package backend --no-dev

# Set working directory back to app location
WORKDIR /app/apps/backend

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI with uvicorn
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

