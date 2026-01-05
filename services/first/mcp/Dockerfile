FROM python:3.14-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install anyio first with specific version to avoid conflicts
RUN pip install --no-cache-dir anyio==3.6.2

# Install core dependencies first
RUN pip install --no-cache-dir \
  mcp>=1.9.1 \
  fastmcp==2.8.1 \
  pydantic==2.7.4 \
  python-dotenv

# Copy MCP server files
COPY services/first/mcp/server.py ./server.py

# Choose a port
EXPOSE 8001

CMD ["python", "server.py"]

