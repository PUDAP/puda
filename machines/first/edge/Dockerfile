FROM python:3.14-slim-bookworm

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Install system dependencies for USB/serial device access, building Python packages, and OpenCV
RUN apt-get update && apt-get install -y \
  build-essential \
  udev \
  libgl1-mesa-glx \
  libglib2.0-0 \
  libgomp1 \
  && rm -rf /var/lib/apt/lists/*

# Install uv for Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

# Copy the entire workspace structure to maintain relative paths
COPY machines/first/edge/ ./machines/first/edge/
COPY libs/drivers/ ./libs/drivers/
COPY libs/comms/ ./libs/comms/

# Install dependencies using uv only for this package
WORKDIR /app/machines/first/edge
RUN uv sync --frozen --no-dev --no-install-project --package first-edge

# Set working directory back to service location
WORKDIR /app/machines/first/edge

# Set Python path to include the workspace
ENV PYTHONPATH=/app/machines/first/edge:/app/libs/drivers/src:/app/libs/comms/src

CMD ["uv", "run", "python", "first.py"]

