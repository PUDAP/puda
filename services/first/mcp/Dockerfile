FROM python:3.14-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
  build-essential \
  curl \
  && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Copy workspace files needed for uv workspace
COPY pyproject.toml uv.lock ./
COPY libs/drivers/pyproject.toml ./libs/drivers/
COPY libs/drivers/src/ ./libs/drivers/src/
COPY services/first/mcp/pyproject.toml ./services/first/mcp/
COPY services/first/mcp/server.py ./services/first/mcp/

# Install dependencies using uv
RUN uv sync --frozen --package first-mcp --no-dev

# Choose a port
EXPOSE 8001

# Run the server using uv
WORKDIR /app/services/first/mcp
CMD ["uv", "run", "python", "server.py"]

