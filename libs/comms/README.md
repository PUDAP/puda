# Puda Comms

A Python module for communication between machines and command services via NATS messaging. Provides client-side services for sending commands, machine-side clients for receiving commands, and data models for structured message exchange.

## Overview

The `puda_comms` module enables asynchronous, reliable communication between command services and machines using NATS (NATS JetStream for guaranteed delivery). It handles:

- **Command execution**: Send commands to machines and receive responses
- **Message routing**: Queue commands (sequential execution) and immediate commands (control operations)
- **State management**: Thread-safe execution state tracking for cancellation and locking
- **Connection management**: Automatic NATS connection handling with async context managers

## Components

The module consists of four main components:

### 1. Models (`models.py`)

Data models for structured message exchange. All models use Pydantic for validation and serialization.

#### Enums

##### `CommandResponseStatus`
Status of a command response:
- `SUCCESS`: Command executed successfully
- `ERROR`: Command execution failed

##### `CommandResponseCode`
Error codes for command responses:
- `COMMAND_CANCELLED`: Command was cancelled before completion
- `JSON_DECODE_ERROR`: Failed to decode JSON payload
- `EXECUTION_ERROR`: General execution error
- `EXECUTION_LOCKED`: Execution is locked (another command is running)
- `UNKNOWN_COMMAND`: Command name not recognized
- `PAUSE_ERROR`: Error occurred while pausing execution
- `RESUME_ERROR`: Error occurred while resuming execution
- `NO_EXECUTION`: No execution found
- `RUN_ID_MISMATCH`: Run ID doesn't match current execution
- `CANCEL_ERROR`: Error occurred while cancelling execution
- `MACHINE_PAUSED`: Machine is currently paused

##### `MessageType`
Type of NATS message:
- `COMMAND`: Command message sent to machine
- `RESPONSE`: Response message from machine
- `LOG`: Log message
- `ALERT`: Alert message
- `MEDIA`: Media message

##### `ImmediateCommand`
Command names for immediate/control commands:
- `PAUSE`: Pause the current execution
- `RESUME`: Resume a paused execution
- `CANCEL`: Cancel the current execution

#### Data Models

##### `CommandRequest`
Represents a command to be sent to a machine.

**Fields:**
- `name` (str): The command name to execute
- `machine_id` (str): Machine ID to send the command to (required)
- `params` (Dict[str, Any]): Command parameters (default: empty dict)
- `step_number` (int): Execution step number for tracking progress
- `version` (str): Command version (default: "1.0")

**Example:**
```python
command = CommandRequest(
    name="attach_tip",
    machine_id="first",
    params={"deck_slot": "A3", "well_name": "G8"},
    step_number=2,
    version="1.0"
)
```

##### `CommandResponse`
Represents the result of a command execution.

**Fields:**
- `status` (CommandResponseStatus): Status of the command response (SUCCESS or ERROR)
- `completed_at` (str): ISO 8601 UTC timestamp (auto-generated)
- `code` (Optional[str]): Error code if status is ERROR
- `message` (Optional[str]): Human-readable error message

**Example:**
```python
response = CommandResponse(
    status=CommandResponseStatus.SUCCESS,
    completed_at="2026-01-20T02:00:46Z"
)
```

**Error Example:**
```python
error_response = CommandResponse(
    status=CommandResponseStatus.ERROR,
    code="EXECUTION_ERROR",
    message="Failed to attach tip: deck_slot A3 not found",
    completed_at="2026-01-20T02:00:46Z"
)
```

##### `MessageHeader`
Header metadata for NATS messages.

**Fields:**
- `message_type` (MessageType): Type of message (COMMAND, RESPONSE, LOG, etc.)
- `version` (str): Message version (default: "1.0")
- `timestamp` (str): ISO 8601 UTC timestamp (auto-generated)
- `user_id` (str): User ID who initiated the command
- `username` (str): Username who initiated the command
- `machine_id` (str): Identifier for the target machine
- `run_id` (Optional[str]): Unique identifier (UUID) for the run/workflow

**Example:**
```python
header = MessageHeader(
    message_type=MessageType.RESPONSE,
    version="1.0",
    timestamp="2026-01-20T02:00:46Z",
    user_id="user123",
    username="John Doe",
    machine_id="first",
    run_id="092073e6-13d0-4756-8d99-eff1612a5a72"
)
```

##### `NATSMessage`
Complete NATS message structure combining header with optional command or response data.

**Fields:**
- `header` (MessageHeader): Message header (required)
- `command` (Optional[CommandRequest]): Command request (for command messages)
- `response` (Optional[CommandResponse]): Command response (for response messages)

**Structure:**
- For command messages: include `header` with `message_type=COMMAND` and `command` field
- For response messages: include `header` with `message_type=RESPONSE` and `response` field

**Complete Message Example:**
```json
{
  "header": {
    "message_type": "response",
    "version": "1.0",
    "timestamp": "2026-01-20T02:00:46Z",
    "user_id": "user123",
    "username": "John Doe",
    "machine_id": "first",
    "run_id": "092073e6-13d0-4756-8d99-eff1612a5a72"
  },
  "command": {
    "name": "attach_tip",
    "params": {
      "deck_slot": "A3",
      "well_name": "G8"
    },
    "step_number": 2,
    "version": "1.0"
  },
  "response": {
    "status": "success",
    "completed_at": "2026-01-20T02:00:46Z",
    "code": null,
    "message": null
  }
}
```

### 2. CommandService (`command_service.py`)

Client-side service for sending commands to machines via NATS. Handles:
- Connecting to NATS servers
- Sending commands to machines (queue or immediate)
- Waiting for and handling responses
- Managing command lifecycle (run_id, step_number, etc.)
- Automatic connection cleanup via async context manager

See [Sending Commands](#sending-commands) section for usage examples.

### 3. EdgeNatsClient (`machine_client.py`)

Basic default NATS client for generic machines. Handles commands, telemetry, and events following the `puda.{machine_id}.{category}.{sub_category}` pattern. Provides:
- Subscribing to command streams (queue and immediate) via JetStream with exactly-once delivery
- Processing incoming commands and sending command responses
- Publishing telemetry (core NATS, no JetStream)
- Publishing events (core NATS, fire-and-forget)
- Connection management and reconnection handling

**Note:** This is a generic client. Machine-specific methods should be implemented in the machine-edge client.

### 4. ExecutionState (`execution_state.py`)

Thread-safe state management for command execution. Provides:
- Execution lock to prevent concurrent commands
- Current task tracking for cancellation
- Run ID matching for cancel operations
- Thread-safe access to execution state

## Sending Commands

The `CommandService` provides a high-level interface for sending commands to machines via NATS. See [`tests/commands.py`](tests/commands.py) and [`tests/batch_commands.py`](tests/batch_commands.py) for complete examples.

### Recommended Usage: Async Context Manager

The recommended way to use `CommandService` is with an async context manager, which automatically handles connection and disconnection. See [`tests/commands.py`](tests/commands.py) for complete examples.

### Command Types

#### Queue Commands

Queue commands are regular commands that are executed in sequence. Use `send_queue_command()` for machine-specific operations.

**Note:** Available commands depend on the machine you are controlling. Different machines support different command sets (e.g., `first` machine supports commands like `load_deck`, `attach_tip`, `aspirate_from`, `dispense_to`, `drop_tip`, etc.).

Both `send_queue_command()`, `send_queue_commands()`, and `send_immediate_command()` accept an optional `timeout` parameter (default: 120 seconds):

```python
# Single command (machine_id must be in CommandRequest)
reply = await service.send_queue_command(
    request=request,  # request.machine_id must be set
    run_id=run_id,
    user_id="user123",
    username="John Doe",
    timeout=60  # Wait up to 60 seconds
)

# Multiple commands (timeout applies to each command)
# Each command in the list must have machine_id set
reply = await service.send_queue_commands(
    requests=commands,  # Each CommandRequest must have machine_id
    run_id=run_id,
    user_id="user123",
    username="John Doe",
    timeout=60  # Wait up to 60 seconds per command
)
```

**Examples:**

See [`tests/commands.py`](tests/commands.py) for complete examples.

#### Immediate Commands

Immediate commands are control commands that interrupt or modify execution. Use `send_immediate_command()` for:
- `pause`: Pause the current execution
- `resume`: Resume a paused execution
- `cancel`: Cancel the current execution

**Examples:**

See [`tests/commands.py`](tests/commands.py) for complete examples.



### Sending Command Sequences

You can send multiple commands in sequence using `send_queue_commands()`, which sends commands one by one and waits for each response before sending the next. If any command fails or times out, it stops immediately and returns the error response.

**Loading Commands from JSON (Recommended for LLM-generated commands):**

When generating commands from an LLM or loading from external sources, you can store commands in a JSON file and load them. See [`tests/batch_commands.py`](tests/batch_commands.py) for a complete example.

### Error Handling

Always check the response status and handle errors appropriately:

```python
reply: NATSMessage = await service.send_queue_command(
    request=request,  # request.machine_id must be set
    run_id=run_id,
    user_id="user123",
    username="John Doe"
)

if reply is None:
    # Command timed out or failed to send
    logger.error("Command failed or timed out")
elif reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
    # Command succeeded
    logger.info("Command completed successfully")
else:
    # Command failed with error
    logger.error("Command failed with code: %s, message: %s", 
                reply.response.code if reply.response else None,
                reply.response.message if reply.response else None)
```

### Configuration

#### NATS Server Configuration

The `CommandService` requires NATS server URLs to be specified explicitly. There are no default values. You must provide servers in one of two ways:

**Option 1: Via environment variable (comma-separated string)**

Set the `NATS_SERVERS` environment variable with comma-separated server URLs:

```bash
export NATS_SERVERS="nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224"
```

Then parse it when creating a `CommandService`:
```python
import os
nats_servers = [s.strip() for s in os.getenv("NATS_SERVERS", "").split(",") if s.strip()]
service = CommandService(servers=nats_servers)
```

**Option 2: Directly as a list**

Specify servers directly when creating a `CommandService`:
```python
service = CommandService(servers=["nats://192.168.50.201:4222", "nats://192.168.50.201:4223", "nats://192.168.50.201:4224"])
```
## Validation

All models use Pydantic for validation, ensuring:
- Type checking for all fields
- Required fields are present
- Default values are applied correctly
- JSON serialization/deserialization works correctly
