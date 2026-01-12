"""
MCP Server Entry Point for First Machine

This file serves as the entry point for fastmcp dev command.
The actual server implementation is in src/server.py.
"""

from src.server import mcp  # noqa: F401

__all__ = ['mcp']

