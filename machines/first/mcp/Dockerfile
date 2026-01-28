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
COPY machines/first/mcp/pyproject.toml ./machines/first/mcp/
COPY machines/first/mcp/server.py ./machines/first/mcp/
COPY machines/first/mcp/src ./machines/first/mcp/src/

# Install dependencies using uv
RUN uv sync --frozen --package first-mcp --no-dev

# Choose a port (update this to match the port in the .env file)
EXPOSE 8001

# Run the server using uv
WORKDIR /app/machines/first/mcp
CMD ["uv", "run", "python", "main.py"]

