# Run State Management & Lifecycle Plan

## Current Implementation

### Command Flow
- Commands sent one-by-one via `CommandService.send_queue_commands()`
- Each command waits for SUCCESS response before sending next
- ERROR response stops the entire sequence
- `run_id` exists in message headers but machines don't validate it

### Existing Components
1. **ExecutionState** (`execution_state.py`)
   - Manages execution lock per machine
   - Tracks current task for cancellation
   - Has `_current_run_id` but only used for cancellation matching

2. **MachineClient** (`machine_client.py`)
   - Handles NATS communication
   - Has `_cancelled_run_ids` set for cancellation
   - Processes queue and immediate commands
   - No run_id validation before executing commands

3. **CommandService** (`command_service.py`)
   - Sends commands to machines
   - `send_queue_commands()` sends sequentially, stops on error

## Proposed Design

### 1. RunManager Class

**Location Decision: `libs/comms/src/puda_comms/run_manager.py`**

**Rationale:**
- Run state management is a communication concern (run_id validation, lifecycle)
- **Only used in `MachineClient` (edge)** - machines track their own active run_id
- CommandService (backend) doesn't need RunManager - it just sends commands
- Keeps machine-specific logic separate from generic run management
- Edge code (`first.py`) imports and uses it via MachineClient, but doesn't define it

**Responsibilities:**
- Track active `run_id` per machine
- Validate `run_id` matches before command execution
- Handle run lifecycle: start → active → complete/reset
- Provide run state queries
- Thread-safe operations

**API Design:**
```python
class RunManager:
    def __init__(self, machine_id: str):
        """
        Args:
            machine_id: Machine identifier
        """
        self.machine_id = machine_id
        self._active_run_id: Optional[str] = None
        self._lock = asyncio.Lock()
    
    async def start_run(self, run_id: str) -> bool:
        """Set active run_id. Returns True if successful, False if run already active."""
        
    async def complete_run(self, run_id: str) -> bool:
        """Clear run_id if it matches. Returns True if successful."""
        
    async def reset_run(self, run_id: Optional[str] = None) -> bool:
        """Force clear run_id (for reset). If run_id provided, only reset if matches."""
        
    async def validate_run_id(self, run_id: Optional[str]) -> bool:
        """Check if run_id matches active run. Returns True if valid."""
        
    def get_active_run_id(self) -> Optional[str]:
        """Get current active run_id."""
```

### 2. Integration Points

#### A. MachineClient Integration

**Changes to `machine_client.py`:**

1. **Add RunManager instance:**
   ```python
   def __init__(self, servers: list[str], machine_id: str):
       # ... existing code ...
       from puda_comms.run_manager import RunManager
       self.run_manager = RunManager(machine_id=machine_id)
   ```

2. **Add run_id validation in `process_queue_cmd()`:**
   
   **Note:** Run lifecycle commands (START, COMPLETE, RESET) are handled before validation. See section 3 below.
   
   For regular commands, validation happens after lifecycle command handling:
   ```python
   # Validation logic (after lifecycle commands are handled)
   if not await self.run_manager.validate_run_id(run_id):
       await msg.ack()  # Ack to prevent redelivery
       await self._publish_command_response(
           msg=msg,
           response=CommandResponse(
               status=CommandResponseStatus.ERROR,
               code=CommandResponseCode.RUN_ID_MISMATCH,
               message=f'Run ID mismatch: expected active run, got {run_id}'
           ),
           subject=self.response_queue
       )
       return
   ```

3. **Handle run lifecycle commands immediately in `process_queue_cmd()` (FIRST, before all other processing):**
   ```python
   async def process_queue_cmd(self, msg: Msg, handler: ...):
       try:
           # Parse message
           message = NATSMessage.model_validate_json(msg.data)
           run_id = message.header.run_id
           command_name = message.command.name.lower() if message.command else None
           
           # Handle run lifecycle commands IMMEDIATELY - before cancellation, pause, validation, or handler execution
           # These commands must execute synchronously to manage run state
           if command_name == 'start':
               if run_id:
                   success = await self.run_manager.start_run(run_id)
                   if not success:
                       # Run already active
                       await msg.ack()
                       await self._publish_command_response(
                           msg=msg,
                           response=CommandResponse(
                               status=CommandResponseStatus.ERROR,
                               code=CommandResponseCode.RUN_ID_MISMATCH,
                               message='cannot start, another run is currently running'
                           ),
                           subject=self.response_queue
                       )
                       return
                   else:
                       await self.publish_state({'state': 'active', 'run_id': run_id})
                       await msg.ack()
                       await self._publish_command_response(
                           msg=msg,
                           response=CommandResponse(status=CommandResponseStatus.SUCCESS),
                           subject=self.response_queue
                       )
                       return
               else:
                   await msg.ack()
                   await self._publish_command_response(
                       msg=msg,
                       response=CommandResponse(
                           status=CommandResponseStatus.ERROR,
                           code=CommandResponseCode.EXECUTION_ERROR,
                           message='START command requires run_id'
                       ),
                       subject=self.response_queue
                   )
                   return
           
           elif command_name == 'complete':
               if run_id:
                   success = await self.run_manager.complete_run(run_id)
                   if success:
                       await self.publish_state({'state': 'idle', 'run_id': None})
                       await msg.ack()
                       await self._publish_command_response(
                           msg=msg,
                           response=CommandResponse(status=CommandResponseStatus.SUCCESS),
                           subject=self.response_queue
                       )
                       return
                   else:
                       await msg.ack()
                       await self._publish_command_response(
                           msg=msg,
                           response=CommandResponse(
                               status=CommandResponseStatus.ERROR,
                               code=CommandResponseCode.RUN_ID_MISMATCH,
                               message=f'Run {run_id} not active'
                           ),
                           subject=self.response_queue
                       )
                       return
               else:
                   # No run_id provided - check if there's an active run
                   active_run_id = self.run_manager.get_active_run_id()
                   if active_run_id:
                       # Complete the active run
                       await self.run_manager.complete_run(active_run_id)
                       await self.publish_state({'state': 'idle', 'run_id': None})
                       await msg.ack()
                       await self._publish_command_response(
                           msg=msg,
                           response=CommandResponse(status=CommandResponseStatus.SUCCESS),
                           subject=self.response_queue
                       )
                       return
                   else:
                       # No active run to complete
                       await msg.ack()
                       await self._publish_command_response(
                           msg=msg,
                           response=CommandResponse(
                               status=CommandResponseStatus.ERROR,
                               code=CommandResponseCode.EXECUTION_ERROR,
                               message='currently nothing running'
                           ),
                           subject=self.response_queue
                       )
                       return
           
           elif command_name == 'reset':
               await self.run_manager.reset_run(run_id)
               await self.publish_state({'state': 'idle', 'run_id': None})
               await msg.ack()
               await self._publish_command_response(
                   msg=msg,
                   response=CommandResponse(status=CommandResponseStatus.SUCCESS),
                   subject=self.response_queue
               )
               return
           
           # For all other commands, continue with normal processing:
           # 1. Check if cancelled
           # 2. Check if paused
           # 3. Validate run_id matches active run
           # 4. Execute handler
           
           # Check if cancelled
           if run_id and run_id in self._cancelled_run_ids:
               # ... existing cancellation logic ...
           
           # Check if paused
           async with self._pause_lock:
               # ... existing pause logic ...
           
           # Validate run_id matches active run
           if not await self.run_manager.validate_run_id(run_id):
               await msg.ack()
               await self._publish_command_response(
                   msg=msg,
                   response=CommandResponse(
                       status=CommandResponseStatus.ERROR,
                       code=CommandResponseCode.RUN_ID_MISMATCH,
                       message=f'Run ID mismatch: expected active run, got {run_id}'
                   ),
                   subject=self.response_queue
               )
               return
           
           # ... rest of existing logic (handler execution, etc.) ...
       except Exception as e:
           # ... existing error handling ...
   ```

#### B. Edge Code Integration (`first.py`)

**Minimal changes needed:**
- RunManager is already instantiated in MachineClient
- Handler logic remains the same for regular commands
- Run validation happens automatically in MachineClient
- START/COMPLETE/RESET are handled in MachineClient, so edge handlers won't see them

**Note:**
- START/COMPLETE/RESET commands are handled by MachineClient before reaching edge handlers
- Edge handlers only process regular machine commands (load_deck, aspirate_from, etc.)
- Edge code can check `client.run_manager.get_active_run_id()` for state queries if needed

#### C. CommandService Integration (Backend)

**Changes to `command_service.py`:**

1. **Add `start_run()` method:**
   ```python
   async def start_run(
       self,
       machine_id: str,
       run_id: str,
       user_id: str,
       username: str,
       timeout: int = 120
   ) -> Optional[NATSMessage]:
       """Send START queue command to begin a run."""
       request = CommandRequest(
           name="start",
           params={},
           step_number=0
       )
       return await self.send_queue_command(
           request=request,
           machine_id=machine_id,
           run_id=run_id,
           user_id=user_id,
           username=username,
           timeout=timeout
       )
   ```

2. **Add `complete_run()` method:**
   ```python
   async def complete_run(
       self,
       machine_id: str,
       run_id: str,
       user_id: str,
       username: str,
       timeout: int = 120
   ) -> Optional[NATSMessage]:
       """Send COMPLETE queue command to end a run."""
       request = CommandRequest(
           name="complete",
           params={},
           step_number=0
       )
       return await self.send_queue_command(
           request=request,
           machine_id=machine_id,
           run_id=run_id,
           user_id=user_id,
           username=username,
           timeout=timeout
       )
   ```

3. **Add `reset_run()` method:**
   ```python
   async def reset_run(
       self,
       machine_id: str,
       run_id: Optional[str] = None,
       user_id: str = "system",
       username: str = "system",
       timeout: int = 120
   ) -> Optional[NATSMessage]:
       """Send RESET queue command to force clear run state."""
       request = CommandRequest(
           name="reset",
           params={},
           step_number=0
       )
       return await self.send_queue_command(
           request=request,
           machine_id=machine_id,
           run_id=run_id,
           user_id=user_id,
           username=username,
           timeout=timeout
       )
   ```

4. **Update `send_queue_commands()` to optionally wrap with start/complete:**
   ```python
   async def send_queue_commands(
       self,
       *,
       requests: list[CommandRequest],
       machine_id: str,
       run_id: str,
       user_id: str,
       username: str,
       timeout: int = 120,
       auto_start: bool = True,
       auto_complete: bool = True
   ) -> Optional[NATSMessage]:
       """
       Send commands with optional automatic run lifecycle management.
       
       If auto_start=True, sends START command before sequence.
       If auto_complete=True, sends COMPLETE command after successful sequence.
       """
   ```

### 3. Run Lifecycle Commands

**Note:** START, COMPLETE, and RESET are **queue commands**, not immediate commands. They are handled specially in `process_queue_cmd()` before run_id validation.

**Command names (regular strings, not enum):**
- `"start"` - Begin a run (sets active run_id)
- `"complete"` - End a run successfully (clears active run_id)
- `"reset"` - Force clear run state (clears active run_id regardless of match)

**Add to `CommandResponseCode` enum:**
```python
RUN_ID_MISMATCH = 'RUN_ID_MISMATCH'  # Already exists!
```

**No changes needed to `ImmediateCommand` enum** - these remain as immediate commands:
- `PAUSE` - Pause current execution
- `RESUME` - Resume paused execution  
- `CANCEL` - Cancel current execution

### 4. Command Sequencing Flow

**New Workflow:**

1. **Backend sends START command:**
   ```python
   await service.start_run(machine_id="first", run_id=run_id, ...)
   ```

2. **Machine receives START:**
   - RunManager sets `_active_run_id = run_id`
   - Machine state → 'busy'
   - Returns SUCCESS

3. **Backend sends queue commands:**
   ```python
   await service.send_queue_commands(
       requests=commands,
       machine_id="first",
       run_id=run_id,  # Must match active run
       ...
   )
   ```

4. **Machine validates each command:**
   - If `run_id` matches active run → execute
   - If `run_id` doesn't match → reject with RUN_ID_MISMATCH

5. **Backend sends COMPLETE command:**
   ```python
   await service.complete_run(machine_id="first", run_id=run_id, ...)
   ```

6. **Machine receives COMPLETE:**
   - RunManager clears `_active_run_id = None`
   - Machine state → 'idle'
   - Returns SUCCESS

**Error Handling:**
- If command fails during sequence, clear the active_run_id

## Implementation Order

1. **Phase 1: Core RunManager**
   - Create `run_manager.py` for per-machine run state tracking
   - Unit tests for RunManager

2. **Phase 2: MachineClient Integration**
   - Add RunManager to MachineClient
   - Handle START/COMPLETE/RESET as special queue commands in `process_queue_cmd()`
   - Add run_id validation in `process_queue_cmd()` (after lifecycle commands)
   - Integration tests

3. **Phase 3: CommandService Integration**
   - Add `start_run()`, `complete_run()`, `reset_run()` methods
   - Update `send_queue_commands()` with optional auto lifecycle
   - Update tests and examples

4. **Phase 4: Edge Code Updates**
   - Test with `first.py`
   - Verify run_id validation works
   - Update documentation

## Benefits

1. **Safety:** Machines only execute commands for active runs
2. **State Management:** Clear lifecycle (start → active → complete)
3. **Error Recovery:** RESET command for stuck states
4. **Per-Machine State:** Each machine independently tracks its own run state
5. **Backward Compatible:** Existing code works (just add START/COMPLETE)
6. **Separation of Concerns:** Run management separate from execution logic

## Open Questions

1. **Should START be required?**
   - Option A: START required before any queue commands
   - Option B: First queue command auto-starts run (backward compatible)
   - A

2. **What happens to queued commands if run completes?**
   - Option A: Reject with RUN_ID_MISMATCH
   - Option B: Auto-start new run (dangerous)
   - A

3. **Should CANCEL also clear run_id?**
   - Option A: Yes, CANCEL → run_id cleared
   - Option B: No, must explicitly COMPLETE or RESET
   - A

4. **Run state persistence?**
   - Should run_id survive machine restart?
   - **Recommendation:** No (start fresh after restart)

## Summary

**Location:** `libs/comms/src/puda_comms/run_manager.py` (imported and used only by MachineClient on edge)

**Key Components:**
- `RunManager` class for run state tracking (only used in MachineClient)
- Integration in `MachineClient.process_queue_cmd()` for lifecycle commands and validation
- New queue commands: START, COMPLETE, RESET (handled specially before validation)
- CommandService methods for sending run lifecycle commands (doesn't use RunManager)

**Flow:**
1. Backend (CommandService) sends START queue command → Machine (MachineClient) sets active run_id via RunManager
2. Backend sends queue commands → Machine validates run_id matches active run (via RunManager)
3. Backend sends COMPLETE queue command → Machine clears run_id (via RunManager)

**Architecture:**
- **Edge (MachineClient):** Uses RunManager to track and validate run state
- **Backend (CommandService):** Only sends commands, doesn't track run state

This design keeps run state management on the machine side where it belongs, while providing a clean API for the backend to manage run lifecycles.

