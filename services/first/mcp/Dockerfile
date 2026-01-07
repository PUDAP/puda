FROM python:3.14-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install uv for Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace files needed for uv workspace
COPY pyproject.toml uv.lock ./
COPY libs/drivers ./libs/drivers/
COPY services/first/mcp/pyproject.toml ./services/first/mcp/
COPY services/first/mcp/server.py ./services/first/mcp/

# Install dependencies using uv
RUN uv sync --frozen --package first-mcp --no-dev

# Choose a port (update this to match the port in the .env file)
EXPOSE 8001

# Run the server using uv
WORKDIR /app/services/first/mcp
CMD ["uv", "run", "python", "server.py"]

