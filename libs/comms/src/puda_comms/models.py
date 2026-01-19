"""
Models for Puda Comms.
"""

from enum import Enum
from typing import Optional, Dict, Any
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
    UNKNOWN_COMMAND = 'UNKNOWN_COMMAND'
    PAUSE_ERROR = 'PAUSE_ERROR'
    RESUME_ERROR = 'RESUME_ERROR'
    NO_EXECUTION = 'NO_EXECUTION'
    RUN_ID_MISMATCH = 'RUN_ID_MISMATCH'
    CANCEL_ERROR = 'CANCEL_ERROR'
    MACHINE_PAUSED = 'MACHINE_PAUSED'


class MessageType(str, Enum):
    """Type of NATS message."""
    COMMAND = 'command'
    RESPONSE = 'response'
    LOG = 'log'
    ALERT = 'alert'
    MEDIA = 'media'


def _get_current_timestamp() -> str:
    """Get current timestamp in ISO 8601 UTC format."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class CommandRequest(BaseModel):
    """Command request data for NATS messages."""
    name: str = Field(description="The command name (string) to send to the machine.")
    params: Dict[str, Any] = Field(default_factory=dict, description="The parameters to send to the machine.")
    step_number: int = Field(description="Execution step number (integer). Used to track the progress of a command.")
    version: str = Field(default="1.0", description="Command version.")


class CommandResponse(BaseModel):
    """Result data in a command response."""
    status: CommandResponseStatus = Field(description="Status of the command response.")
    completed_at: str = Field(default_factory=_get_current_timestamp, description="ISO format timestamp (auto-set on creation)")
    code: Optional[str] = Field(default=None, description="Error code (e.g., 'COMMAND_CANCELLED', 'HANDLER_ERROR')")
    message: Optional[str] = Field(default=None, description="Error message (human-readable description)")

class MessageHeader(BaseModel):
    """Header for NATS messages."""
    message_type: MessageType = Field(description="Type of message")
    version: str = Field(default="1.0", description="Message version")
    timestamp: str = Field(default_factory=_get_current_timestamp, description="ISO format timestamp (auto-set on creation)")
    machine_id: str = Field(description="Machine ID")
    run_id: Optional[str] = Field(default=None, description="Unique identifier (uuid) for the run/workflow")

class NATSMessage(BaseModel):
    """
    Complete NATS message structure.
    
    Structure:
    - header: MessageHeader with message_type, version, timestamp, machine_id, run_id
    - command: Optional CommandRequest (for command messages)
    - response: Optional CommandResponse data (for response messages)
    """
    header: MessageHeader = Field(description="Header of the NATS message.")
    command: Optional[CommandRequest] = Field(default=None, description="Command request (for command messages)")
    response: Optional[CommandResponse] = Field(default=None, description="Command response (for response messages)")