FROM python:3.12-slim-bookworm

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace root and all relevant members so uv can resolve {workspace=true} sources
COPY pyproject.toml uv.lock ./
COPY libs/comms/    ./libs/comms/
COPY libs/drivers/  ./libs/drivers/

WORKDIR /app/libs/drivers/opentrons_driver/edge
RUN uv sync --frozen --no-dev --package ot2-edge

CMD ["uv", "run", "python", "main.py"]
