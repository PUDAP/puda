"""
MCP Tools for First Machine

Provides tools for interacting with the First machine and generating protocols.
"""

from .machine_status import get_machine_status
from .protocol_generation import generate_machine_commands

__all__ = [
    'get_machine_status',
    'generate_machine_commands',
]

