FROM python:3.14-slim-bookworm

WORKDIR /app

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install uv for Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy the root workspace configuration
COPY pyproject.toml ./pyproject.toml

# Copy the entire workspace structure to maintain relative paths
COPY services/logger/ ./services/logger/
COPY libs/db/ ./libs/db/
COPY libs/python-sdk/ ./libs/python-sdk/

# Install dependencies using uv from the service directory
WORKDIR /app/services/logger
RUN uv sync --no-dev

# Set working directory back to service location
WORKDIR /app/services/logger

# Set Python path to include the workspace
ENV PYTHONPATH=/app/services/logger:/app/libs/db/src:/app/libs/python-sdk/src

CMD ["uv", "run", "python", "main.py"]
