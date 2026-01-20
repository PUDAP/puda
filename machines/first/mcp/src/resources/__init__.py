"""
MCP Resources for First Machine

Provides resources that expose machine capabilities and configuration.
"""

from .commands import get_available_commands_data
from .labware import get_available_labware_resource

__all__ = [
    'get_available_labware_resource',
    'get_available_commands_data',
]

