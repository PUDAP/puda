# Puda Comms Models

This module defines the data models used for communication between machines and the command service via NATS messaging.

## Overview

The models provide a structured way to send commands to machines and receive responses. All models are built using Pydantic for validation and serialization.

## Core Models

### Enums

#### `CommandResponseStatus`
Status of a command response:
- `SUCCESS`: Command executed successfully
- `ERROR`: Command execution failed

#### `CommandResponseCode`
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

#### `MessageType`
Type of NATS message:
- `COMMAND`: Command message sent to machine
- `RESPONSE`: Response message from machine
- `LOG`: Log message
- `ALERT`: Alert message
- `MEDIA`: Media message

### Data Models

#### `CommandRequest`
Represents a command to be sent to a machine.

**Fields:**
- `name` (str): The command name to execute
- `params` (Dict[str, Any]): Command parameters (default: empty dict)
- `step_number` (int): Execution step number for tracking progress
- `version` (str): Command version (default: "1.0")

**Example:**
```python
command = CommandRequest(
    name="attach_tip",
    params={"slot": "A3", "well": "G8"},
    step_number=2,
    version="1.0"
)
```

#### `CommandResponse`
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

**Error Example**
```python
error_response = CommandResponse(
    status=CommandResponseStatus.ERROR,
    code="EXECUTION_ERROR",
    message="Failed to attach tip: slot A3 not found",
    completed_at="2026-01-20T02:00:46Z"
)
```

#### `MessageHeader`
Header metadata for NATS messages.

**Fields:**
- `message_type` (MessageType): Type of message (COMMAND, RESPONSE, LOG, etc.)
- `version` (str): Message version (default: "1.0")
- `timestamp` (str): ISO 8601 UTC timestamp (auto-generated)
- `machine_id` (str): Identifier for the target machine
- `run_id` (Optional[str]): Unique identifier (UUID) for the run/workflow

**Example:**
```python
header = MessageHeader(
    message_type=MessageType.RESPONSE,
    version="1.0",
    timestamp="2026-01-20T02:00:46Z",
    machine_id="first",
    run_id="092073e6-13d0-4756-8d99-eff1612a5a72"
)
```

#### `NATSMessage`
Complete NATS message structure combining header with optional command or response data.

**Fields:**
- `header` (MessageHeader): Message header (required)
- `command` (Optional[CommandRequest]): Command request (for command messages)
- `response` (Optional[CommandResponse]): Command response (for response messages)

**Structure:**
- For command messages: include `header` with `message_type=COMMAND` and `command` field
- For response messages: include `header` with `message_type=RESPONSE` and `response` field

## Example Usage

### Complete Message Example

Here's an example of a complete NATS message with a response:

```json
{
  "header": {
    "message_type": "response",
    "version": "1.0",
    "timestamp": "2026-01-20T02:00:46Z",
    "machine_id": "first",
    "run_id": "092073e6-13d0-4756-8d99-eff1612a5a72"
  },
  "command": {
    "name": "attach_tip",
    "params": {
      "slot": "A3",
      "well": "G8"
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


## Sending Commands

The `CommandService` provides a high-level interface for sending commands to machines via NATS. See [`tests/command_service.py`](tests/command_service.py) for complete examples.

### CommandService Overview

The `CommandService` handles:
- Connecting to NATS servers
- Sending commands to machines (queue or immediate)
- Waiting for and handling responses
- Managing command lifecycle (run_id, step_number, etc.)
- Automatic connection cleanup via async context manager

### Recommended Usage: Async Context Manager

The recommended way to use `CommandService` is with an async context manager, which automatically handles connection and disconnection:

```python
import uuid
import asyncio
import logging
from puda_comms import CommandService
from puda_comms.models import CommandRequest, CommandResponseStatus, NATSMessage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def send_command():
    run_id = str(uuid.uuid4())
    
    # Using async context manager - automatically connects and disconnects
    async with CommandService() as service:
        request = CommandRequest(
            name="attach_tip",
            params={"slot": "A3", "well": "G8"},
            step_number=2
        )
        reply: NATSMessage = await service.send_queue_command(
            request=request,
            machine_id="first",
            run_id=run_id
        )
        
        if reply is None:
            logger.error("Command failed or timed out")
            return
        
        if reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Command completed successfully")
        else:
            logger.warning("Command failed with code: %s, message: %s", 
                         reply.response.code if reply.response else None,
                         reply.response.message if reply.response else None)

asyncio.run(send_command())
```

### Command Types

#### Queue Commands

Queue commands are regular commands that are executed in sequence. Use `send_queue_command()` for:
- Labware operations (`load_labware`, `remove_labware`)
- Tip operations (`attach_tip`, `drop_tip`)
- Liquid handling (`aspirate_from`, `dispense_to`)
- Deck operations (`load_deck`)

**Examples:**

Load labware:
```python
async def load_labware(run_id: str):
    """Example: Send a single command using context manager."""
    async with CommandService() as service:
        request = CommandRequest(
            name="load_labware",
            params={
                "slot": "A1",
                "labware_name": "opentrons_96_tiprack_300ul"
            },
            step_number=1
        )
        reply: NATSMessage = await service.send_queue_command(
            request=request,
            machine_id="first",
            run_id=run_id
        )
        
        if reply is None:
            logger.error("Command failed or timed out")
            return
        
        if reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Command completed successfully")
        else:
            logger.warning("Command failed with code: %s, message: %s", 
                         reply.response.code, reply.response.message)
```

Remove labware:
```python
async def remove_labware(run_id: str):
    """Example: Send a single command using context manager."""
    async with CommandService() as service:
        request = CommandRequest(
            name="remove_labware",
            params={
                "slot": "A1"
            },
            step_number=1
        )
        reply: NATSMessage = await service.send_queue_command(
            request=request,
            machine_id="first",
            run_id=run_id
        )
        
        if reply is None:
            logger.error("Command failed or timed out")
            return
        
        if reply.response is not None and reply.response.status == CommandResponseStatus.SUCCESS:
            logger.info("Labware removed successfully")
        else:
            logger.error("Failed to remove labware: %s", reply.response.message)
```

#### Immediate Commands

Immediate commands are control commands that interrupt or modify execution. Use `send_immediate_command()` for:
- `pause`: Pause the current execution
- `resume`: Resume a paused execution
- `cancel`: Cancel the current execution

**Examples:**

Pause:
```python
async def example_pause(run_id: str):
    """Example: Send pause command using context manager."""
    async with CommandService() as service:
        pause_request = CommandRequest(
            name="pause",
            step_number=1
        )
        reply: NATSMessage = await service.send_immediate_command(
            request=pause_request,
            machine_id="first",
            run_id=run_id
        )
        if reply is not None:
            logger.info("Pause command result: status=%s, message=%s", 
                      reply.response.status, reply.response.message)
        else:
            logger.error("Pause command failed or timed out")
```

Resume:
```python
async def example_resume(run_id: str):
    """Example: Send resume command using context manager."""
    async with CommandService() as service:
        resume_request = CommandRequest(
            name="resume",
            step_number=1
        )
        reply: NATSMessage = await service.send_immediate_command(
            request=resume_request,
            machine_id="first",
            run_id=run_id
        )
        if reply:
            logger.info("Resume command result: status=%s, message=%s", 
                      reply.response.status, reply.response.message)
        else:
            logger.error("Resume command failed or timed out")
```

Cancel:
```python
async def example_cancel(run_id: str):
    """Example: Send cancel command using context manager."""
    async with CommandService() as service:
        cancel_request = CommandRequest(
            name="cancel",
            step_number=1
        )
        reply = await service.send_immediate_command(
            request=cancel_request,
            machine_id="first",
            run_id=run_id
        )
        if reply:
            logger.info("Cancel command result: status=%s, message=%s", 
                      reply.response.status, reply.response.message)
        else:
            logger.error("Cancel command failed or timed out")
```

### Sending Command Sequences

You can send multiple commands in sequence by looping through them:

```python
async def example_command_sequence(run_id: str):
    """Example: Send a sequence of commands using context manager."""
    async with CommandService() as service:
        commands = [
            {
                "name": "load_deck",
                "params": {
                    "deck_layout": {
                        "C1": "trash_bin",
                        "C2": "polyelectric_8_wellplate_30000ul",
                        "A3": "opentrons_96_tiprack_300ul"
                    }
                },
                "step_number": 1
            },
            {
                "name": "attach_tip",
                "params": {"slot": "A3", "well": "G8"},
                "step_number": 2
            },
            {
                "name": "aspirate_from",
                "params": {"slot": "P0", "well": "A1", "amount": 100},
                "step_number": 3
            },
            {
                "name": "dispense_to",
                "params": {"slot": "C2", "well": "B4", "amount": 100},
                "step_number": 4
            },
            {
                "name": "drop_tip",
                "params": {"slot": "C1", "well": "A1"},
                "step_number": 5
            }
        ]
        
        all_succeeded = True
        for cmd in commands:
            request = CommandRequest(
                name=cmd.get('name'),
                params=cmd.get('params', {}),
                step_number=cmd.get('step_number')
            )
            reply: NATSMessage = await service.send_queue_command(
                request=request,
                machine_id="first",
                run_id=run_id
            )
            
            if reply is None:
                logger.error("Command failed or timed out: %s (step %s)", 
                           request.name, request.step_number)
                all_succeeded = False
                break
            
            if reply.response is not None and reply.response.status != CommandResponseStatus.SUCCESS:
                logger.error("Command failed: %s (step %s) - code: %s, message: %s", 
                          request.name, request.step_number, 
                          reply.response.code, reply.response.message)
                all_succeeded = False
                break
            
            logger.info("Command succeeded: %s (step %s)", request.name, request.step_number)
        
        if all_succeeded:
            logger.info("All commands completed successfully")
        else:
            logger.error("Command sequence failed")
```

### Error Handling

Always check the response status and handle errors appropriately:

```python
reply: NATSMessage = await service.send_queue_command(
    request=request,
    machine_id="first",
    run_id=run_id
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

The `CommandService` reads NATS server URLs from the `NATS_SERVERS` environment variable, or defaults to:
```
nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224
```

You can also specify servers explicitly:
```python
service = CommandService(servers=["nats://localhost:4222"])
```

### Timeout

Both `send_queue_command()` and `send_immediate_command()` accept an optional `timeout` parameter (default: 30 seconds):

```python
reply = await service.send_queue_command(
    request=request,
    machine_id="first",
    run_id=run_id,
    timeout=60  # Wait up to 60 seconds
)
```

## Timestamps

All timestamps are automatically generated in ISO 8601 UTC format (`YYYY-MM-DDTHH:MM:SSZ`) when models are created. The `completed_at` field in `CommandResponse` and `timestamp` field in `MessageHeader` both use this format.

## Validation

All models use Pydantic for validation, ensuring:
- Type checking for all fields
- Required fields are present
- Default values are applied correctly
- JSON serialization/deserialization works correctly

