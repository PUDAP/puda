"""
MCP Server for First Machine

Entry point and FastMCP initialization.
"""

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Config
from .dependencies import lifespan
from .tools import get_machine_state
from .resources import get_available_labware_resource, get_available_commands_data


# Initialize FastMCP server with lifespan management
mcp = FastMCP(
    name=Config.SERVER_NAME,
    version=Config.SERVER_VERSION,
    instructions=f"This MCP server provides tools for generating protocols and workflows for the {Config.MACHINE_ID} machine.",
    lifespan=lifespan,
)

# Register tools using explicit registration pattern
mcp.tool(
    name="get_machine_state",
    description="Get the current status of the machine from NATS Key-Value store"
)(get_machine_state)

# mcp.tool(
#     name="generate_machine_commands",
#     description="Generate machine commands from natural language instructions for the First machine"
# )(generate_machine_commands)

# Register resources using explicit registration pattern
def get_machine_id() -> str:
    """Return the machine ID."""
    return Config.MACHINE_ID

mcp.resource(
    uri="resource://first/machine_id",
    name="Machine ID",
    description="The ID of the machine"
)(get_machine_id)

mcp.resource(
    uri="resource://first/labware",
    name="Available Labware",
    description="A list of all available labware types for the First machine"
)(get_available_labware_resource)

mcp.resource(
    uri="resource://first/commands",
    name="Available Commands",
    description="A JSON object describing all available First machine commands and their parameters"
)(get_available_commands_data)


@mcp.custom_route("/", methods=["GET"])
async def root(_request: Request) -> JSONResponse:
    """Root endpoint that returns server information."""
    return JSONResponse({
        "name": Config.SERVER_NAME,
        "version": Config.SERVER_VERSION,
        "status": "running",
        "mcp_endpoint": "/mcp"
    })


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "healthy"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=Config.SERVER_PORT)

