"""
Models for Puda Comms.
"""

from enum import Enum
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class CommandResponseStatus(str, Enum):
    """Status of a command response."""
    SUCCESS = 'success'
    ERROR = 'error'


class CommandResponseCode(str, Enum):
    """Error codes for command responses."""
    COMMAND_CANCELLED = 'COMMAND_CANCELLED'
    JSON_DECODE_ERROR = 'JSON_DECODE_ERROR'
    EXECUTION_ERROR = 'EXECUTION_ERROR'
    EXECUTION_LOCKED = 'EXECUTION_LOCKED'
    HANDLER_ERROR = 'HANDLER_ERROR'
    PAUSE_ERROR = 'PAUSE_ERROR'
    RESUME_ERROR = 'RESUME_ERROR'
    NO_EXECUTION = 'NO_EXECUTION'
    RUN_ID_MISMATCH = 'RUN_ID_MISMATCH'
    CANCEL_ERROR = 'CANCEL_ERROR'


def _get_current_timestamp() -> str:
    """Get current timestamp in ISO 8601 UTC format."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class CommandResponse(BaseModel):
    """Result data in a command response."""
    status: CommandResponseStatus
    completed_at: str = Field(default_factory=_get_current_timestamp)  # ISO format timestamp (auto-set on creation)
    code: Optional[str] = None  # Error code (e.g., "INVALID_TOKEN")
    message: Optional[str] = None  # Error message (human-readable description)