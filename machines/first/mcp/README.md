# First Machine MCP Server

MCP (Model Context Protocol) server for generating protocols and workflows for the First lab automation machine.

## Resources

The server provides the following resources:

- **`resource://first/commands`** - A JSON object describing all available First machine commands and their parameters, including examples and documentation.
- **`resource://first/labware`** - A JSON array of all available labware types for the First machine.

## Development

### 1. The FastMCP Dev GUI (Recommended)

Since you are using fastmcp, the easiest way to test tools is to use its built-in developer interface. This launches a web UI where you can list tools and run them interactively.

```bash
cd machines/first/mcp
uv run fastmcp dev main.py
```

for prod

```bash
uv run python -m src.server
```

This will start a development server with a web interface where you can:
- View all available tools and resources
- Test tools interactively
- See tool responses and errors
- Access resources

## Docker Deployment

See the main [First Edge Service README](../README.md) for Docker deployment instructions.

The MCP server runs as a separate container and can be started independently:

```bash
cd machines/first/mcp
docker compose up -d
```

The server will be available at `http://localhost:8001`.

