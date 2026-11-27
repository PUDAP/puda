"""
Models for Puda Comms.
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .constants import PROTOCOL_VERSION


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
    MISSING_RUN_ID = 'MISSING_RUN_ID'
    CANCEL_ERROR = 'CANCEL_ERROR'
    MACHINE_PAUSED = 'MACHINE_PAUSED'
    MACHINE_ESTOPPED = 'MACHINE_ESTOPPED'
    ESTOP_NOT_SUPPORTED = 'ESTOP_NOT_SUPPORTED'


class MessageType(str, Enum):
    """Type of NATS message."""
    COMMAND = 'command'
    RESPONSE = 'response'
    LOG = 'log'
    ALERT = 'alert'
    MEDIA = 'media'


class ImmediateCommand(str, Enum):
    """Command names for immediate commands."""
    START = 'start'
    COMPLETE = 'complete'
    PAUSE = 'pause'
    RESUME = 'resume'
    RESET = 'reset'
    ESTOP = 'estop'


class MachineState(str, Enum):
    """Machine state values persisted to the machine state KV store."""
    # No queued command is executing; run_id may be set when a run has started.
    IDLE = 'idle'
    # A queued command is currently executing.
    BUSY = 'busy'
    # The queue is paused and will not start queued commands until resumed.
    PAUSED = 'paused'
    # The last state transition or command failed.
    ERROR = 'error'
    # Emergency stop latched; queued commands are rejected until a successful reset.
    ESTOPPED = 'estopped'
    # The edge is shutting down or disconnected cleanly.
    OFFLINE = 'offline'


def _get_current_timestamp() -> str:
    """Get current timestamp in ISO 8601 UTC format."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class CommandRequest(BaseModel):
    """Command request data for NATS messages."""
    # Fields from a newer protocol minor are kept, so the response echoes them (§8.1).
    model_config = ConfigDict(extra="allow")
    name: str = Field(description="The command name (string) to send to the machine.")
    params: Dict[str, Any] = Field(default_factory=dict, description="The parameters to send to the machine.")
    kwargs: Dict[str, Any] = Field(default_factory=dict, description="Additional keyword arguments (e.g., channels in Biologic).")
    step_number: int = Field(description="Execution step number (integer). Used to track the progress of a command.")
    machine_id: str = Field(description="Machine ID to send the command to.")


class CommandResponse(BaseModel):
    """Result data in a command response."""
    status: CommandResponseStatus = Field(description="Status of the command response.")
    completed_at: str = Field(default_factory=_get_current_timestamp, description="ISO format timestamp (auto-set on creation)")
    # A newer protocol minor may add codes; keep an unknown one as its string.
    code: Optional[CommandResponseCode | str] = Field(
        default=None, union_mode="left_to_right", description="Error code"
    )
    message: Optional[str] = Field(default=None, description="Error message (human-readable description)")
    data: Optional[Dict[Any, Any]] = Field(default=None, description="Optional output data from the command handler")

class MessageHeader(BaseModel):
    """Header for NATS messages."""
    model_config = ConfigDict(extra="allow")
    protocol_version: str = Field(description="PUDA Edge Protocol version (MAJOR.MINOR); required")
    message_type: MessageType = Field(description="Type of message")
    user_id: str = Field(description="User ID")
    username: str = Field(description="User name")
    machine_id: str = Field(description="Machine ID")
    run_id: Optional[str] = Field(default=None, description="Unique identifier (uuid) for the run/workflow")
    timestamp: str = Field(default_factory=_get_current_timestamp, description="ISO format timestamp (auto-set on creation)")

    @field_validator("protocol_version")
    @classmethod
    def _same_protocol_major(cls, value: str) -> str:
        """Accept MAJOR.MINOR with this SDK's major; a new major is breaking."""
        major, _, minor = value.partition(".")
        if not (major.isdecimal() and minor.isdecimal()) or major != PROTOCOL_VERSION.partition(".")[0]:
            raise ValueError(f"unsupported protocol version {value!r}; this SDK speaks {PROTOCOL_VERSION}")
        return value

class NATSMessage(BaseModel):
    """
    Complete NATS message structure.
    
    Structure:
    - header: MessageHeader with protocol_version, message_type, timestamp, user_id, username, machine_id, run_id
    - command: Optional CommandRequest (for command messages)
    - response: Optional CommandResponse data (for response messages)

    Unknown fields are kept and echoed unchanged in responses (spec §8.1).
    """
    model_config = ConfigDict(extra="allow")
    header: MessageHeader = Field(description="Header of the NATS message.")
    command: Optional[CommandRequest] = Field(default=None, description="Command request (for command messages)")
    response: Optional[CommandResponse] = Field(default=None, description="Command response (for response messages)")
