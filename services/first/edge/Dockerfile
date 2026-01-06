FROM python:3.14-slim-bookworm

WORKDIR /app

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

# Copy the entire workspace structure to maintain relative paths
COPY services/first/edge/ ./services/first/edge/
COPY libs/drivers/ ./libs/drivers/
COPY libs/comms/ ./libs/comms/

# Install dependencies using uv from the service directory
WORKDIR /app/services/first/edge
RUN uv sync --frozen --no-dev

# Set working directory back to service location
WORKDIR /app/services/first/edge

# Set Python path to include the workspace
ENV PYTHONPATH=/app/services/first/edge:/app/libs/drivers/src:/app/libs/comms/src

CMD ["uv", "run", "python", "first.py"]

