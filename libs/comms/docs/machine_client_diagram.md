# EdgeNatsClient Message Handling Flow

This diagram shows how `EdgeNatsClient` processes incoming messages from NATS JetStream.

## Queue Commands Flow

```mermaid
flowchart TD
    Start([Message Received<br/>from COMMAND_QUEUE stream]) --> Parse[Parse JSON to NATSMessage]
    Parse --> Extract[Extract run_id, step_number, command]
    
    Extract --> CheckPaused{_is_paused?<br/>with _pause_lock}
    CheckPaused -->|Yes| ResponsePaused[Publish Response:<br/>MACHINE_PAUSED<br/>Return immediately]
    ResponsePaused --> End1([End])
    
    CheckPaused -->|No| WaitLoop[While paused loop:<br/>Release lock<br/>msg.in_progress<br/>sleep 1s<br/>Recheck _is_paused with lock]
    WaitLoop --> StillPaused{Still<br/>paused?}
    StillPaused -->|Yes| WaitLoop
    StillPaused -->|No| ValidateRunId{run_id<br/>is None?}
    ValidateRunId -->|Yes| AckNoRunId[msg.ack]
    AckNoRunId --> ResponseNoRunId[Publish Response:<br/>EXECUTION_ERROR<br/>'Command requires run_id']
    ResponseNoRunId --> End2([End])
    
    ValidateRunId -->|No| CheckActiveRun{Active run_id<br/>is None?}
    CheckActiveRun -->|Yes| AckNoActive[msg.ack]
    AckNoActive --> ResponseNoActive[Publish Response:<br/>RUN_ID_MISMATCH<br/>'Send START command first']
    ResponseNoActive --> End3([End])
    
    CheckActiveRun -->|No| ValidateMatch{run_id matches<br/>active run_id?}
    ValidateMatch -->|No| AckMismatch[msg.ack]
    AckMismatch --> ResponseMismatch[Publish Response:<br/>RUN_ID_MISMATCH]
    ResponseMismatch --> End4([End])
    
    ValidateMatch -->|Yes| KeepAlive[Start Keep-Alive<br/>Background Task]
    KeepAlive --> Execute[Execute Handler<br/>with _keep_message_alive]
    
    Execute --> HandlerSuccess{Handler<br/>Success?}
    HandlerSuccess -->|Exception| ExceptionHandler{Exception<br/>Type?}
    
    ExceptionHandler -->|CancelledError| AckCancelled[msg.ack]
    AckCancelled --> ResponseCancelled[Publish Response:<br/>COMMAND_CANCELLED]
    ResponseCancelled --> End5([End])
    
    ExceptionHandler -->|JSONDecodeError| TermJSON[msg.term]
    TermJSON --> ResponseJSON[Publish Response:<br/>JSON_DECODE_ERROR]
    ResponseJSON --> End6([End])
    
    ExceptionHandler -->|Other Exception| TermError[msg.term]
    TermError --> ResponseError[Publish Response:<br/>EXECUTION_ERROR]
    ResponseError --> End7([End])
    
    HandlerSuccess -->|Success| CheckStatus{Response<br/>Status?}
    CheckStatus -->|SUCCESS| AckSuccess[msg.ack]
    CheckStatus -->|ERROR| TermSuccess[msg.term]
    
    AckSuccess --> PublishResponse[Publish Response<br/>to RESPONSE_QUEUE stream]
    TermSuccess --> PublishResponse
    PublishResponse --> End8([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End1 fill:#ffe1e1,color:#000000
    style End2 fill:#ffe1e1,color:#000000
    style End3 fill:#ffe1e1,color:#000000
    style End4 fill:#ffe1e1,color:#000000
    style End5 fill:#ffe1e1,color:#000000
    style End6 fill:#ffe1e1,color:#000000
    style End7 fill:#ffe1e1,color:#000000
    style End8 fill:#d4edda,color:#000000
    style KeepAlive fill:#fff3cd,color:#000000
    style Execute fill:#d1ecf1,color:#000000
    style ValidateRunId fill:#fff3cd,color:#000000
    style CheckActiveRun fill:#fff3cd,color:#000000
    style ValidateMatch fill:#fff3cd,color:#000000
```

## Immediate Commands Flow

```mermaid
flowchart TD
    Start([Message Received<br/>from COMMAND_IMMEDIATE stream]) --> Parse[Parse JSON to NATSMessage]
    Parse --> AckImmediate[msg.ack<br/>Immediately]
    
    AckImmediate --> CheckCommand{Command<br/>Type?}
    
    CheckCommand -->|START| StartLogic{run_id<br/>provided?}
    StartLogic -->|No| ResponseStartError[Response:<br/>MISSING_RUN_ID]
    StartLogic -->|Yes| StartRun[run_manager.start_run<br/>run_id]
    StartRun --> StartSuccess{Success?}
    StartSuccess -->|No| ResponseStartMismatch[Response:<br/>RUN_ID_MISMATCH<br/>'another run active']
    StartSuccess -->|Yes| PublishStartState[Publish State:<br/>'active', run_id]
    PublishStartState --> ResponseStartSuccess[Response: SUCCESS]
    
    CheckCommand -->|COMPLETE| CompleteLogic{run_id<br/>provided?}
    CompleteLogic -->|No| ResponseCompleteError[Response:<br/>MISSING_RUN_ID]
    CompleteLogic -->|Yes| CompleteRun[run_manager.complete_run<br/>run_id]
    CompleteRun --> CompleteSuccess{Success?}
    CompleteSuccess -->|No| ResponseCompleteMismatch[Response:<br/>RUN_ID_MISMATCH<br/>'run not active']
    CompleteSuccess -->|Yes| PublishCompleteState[Publish State:<br/>'idle', run_id: None]
    PublishCompleteState --> ResponseCompleteSuccess[Response: SUCCESS]
    
    CheckCommand -->|PAUSE| PauseLogic[Set _is_paused = True<br/>with _pause_lock<br/>Publish State: 'paused']
    CheckCommand -->|RESUME| ResumeLogic[Set _is_paused = False<br/>with _pause_lock<br/>Publish State: 'idle']
    CheckCommand -->|CANCEL| CancelLogic{run_id<br/>provided?}
    CancelLogic -->|No| ResponseCancelError[Response:<br/>MISSING_RUN_ID]
    CancelLogic -->|Yes| CancelRun[run_manager.complete_run<br/>run_id<br/>Publish State: 'idle']
    CancelRun --> ExecuteHandler[Execute Handler]
    
    PauseLogic --> ExecuteHandler
    ResumeLogic --> ExecuteHandler
    
    ResponseStartSuccess --> PublishResponse[Publish Response<br/>to RESPONSE_IMMEDIATE stream]
    ResponseStartError --> PublishResponse
    ResponseStartMismatch --> PublishResponse
    ResponseCompleteSuccess --> PublishResponse
    ResponseCompleteError --> PublishResponse
    ResponseCompleteMismatch --> PublishResponse
    ResponseCancelError --> PublishResponse
    ExecuteHandler --> HandlerResult{Handler<br/>Result?}
    
    HandlerResult -->|Success| PublishResponse
    HandlerResult -->|Exception| ExceptionType{Exception<br/>Type?}
    
    ExceptionType -->|JSONDecodeError| ResponseJSON[Publish Response:<br/>JSON_DECODE_ERROR<br/>Publish State: 'error']
    ExceptionType -->|Other| ResponseError[Publish Response:<br/>EXECUTION_ERROR<br/>Publish State: 'error']
    
    ResponseJSON --> End1([End])
    ResponseError --> End1
    PublishResponse --> End2([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End1 fill:#ffe1e1,color:#000000
    style End2 fill:#d4edda,color:#000000
    style AckImmediate fill:#fff3cd,color:#000000
    style ExecuteHandler fill:#d1ecf1,color:#000000
    style StartRun fill:#d1ecf1,color:#000000
    style CompleteRun fill:#d1ecf1,color:#000000
    style CancelRun fill:#d1ecf1,color:#000000
```

## Keep-Alive Mechanism

```mermaid
flowchart LR
    Start([Handler Execution<br/>Starts]) --> CreateTask[Create Background Task]
    CreateTask --> Loop[Every 25 seconds]
    Loop --> InProgress[msg.in_progress<br/>Reset Redelivery Timer]
    InProgress --> Loop
    
    Start --> Handler[Handler Running]
    Handler --> Complete[Handler Completes]
    Complete --> CancelTask[Cancel Background Task]
    CancelTask --> End([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End fill:#d4edda,color:#000000
    style InProgress fill:#fff3cd,color:#000000
    style Handler fill:#d1ecf1,color:#000000
```

## Complete Message Flow Overview

```mermaid
flowchart TB
    subgraph NATS["NATS JetStream"]
        QueueStream[COMMAND_QUEUE Stream<br/>WorkQueue Retention]
        ImmediateStream[COMMAND_IMMEDIATE Stream<br/>WorkQueue Retention]
        ResponseQueue[RESPONSE_QUEUE Stream<br/>Interest Retention]
        ResponseImmediate[RESPONSE_IMMEDIATE Stream<br/>Interest Retention]
    end
    
    subgraph Client["EdgeNatsClient"]
        QueueSub[subscribe_queue<br/>Durable Consumer]
        ImmediateSub[subscribe_immediate<br/>Durable Consumer]
        
        QueueSub --> ProcessQueue[process_queue_cmd]
        ImmediateSub --> ProcessImmediate[process_immediate_cmd]
        
        ProcessQueue --> QueueHandler[User Handler]
        ProcessImmediate --> ImmediateHandler[User Handler]
        
        QueueHandler --> ResponsePub[Publish Response]
        ImmediateHandler --> ResponsePub
    end
    
    subgraph State["State Management"]
        PauseLock[_pause_lock]
        IsPaused[_is_paused]
        RunManager[RunManager<br/>Tracks active_run_id<br/>Validates run_id matches]
        KeepAliveTask[Keep-Alive Task<br/>25s interval]
    end
    
    NATS --> Client
    Client --> State
    ResponsePub --> NATS
    
    style QueueStream fill:#e1f5ff,color:#000000
    style ImmediateStream fill:#e1f5ff,color:#000000
    style ResponseQueue fill:#d4edda,color:#000000
    style ResponseImmediate fill:#d4edda,color:#000000
    style ProcessQueue fill:#fff3cd,color:#000000
    style ProcessImmediate fill:#fff3cd,color:#000000
    style KeepAliveTask fill:#ffe1e1,color:#000000
```

## Key Features

### Queue Commands (`process_queue_cmd`)
- **Pause Check**: First checks if paused (with lock), publishes MACHINE_PAUSED response and returns immediately
- **Pause Wait Loop**: If paused, waits in loop (releasing lock, calling in_progress, sleeping 1s) until resumed
- **Run ID Validation**: 
  - Validates run_id is not None
  - Validates active_run_id exists (requires START command first)
  - Validates run_id matches active_run_id using RunManager
- **Keep-Alive**: Background task resets redelivery timer every 25 seconds
- **Ack/Term Logic**: 
  - `msg.ack()` on SUCCESS, CANCELLED, or validation errors
  - `msg.term()` on ERROR (prevents infinite redelivery)
- **Error Handling**: Handles JSON decode errors, cancellation, and execution errors separately

### Immediate Commands (`process_immediate_cmd`)
- **Immediate Ack**: Acknowledges message immediately after parsing
- **Built-in Commands**: 
  - **START**: Uses `run_manager.start_run()` to set active run_id, publishes state 'active'
  - **COMPLETE**: Uses `run_manager.complete_run()` to clear active run_id, publishes state 'idle'
  - **PAUSE**: Sets `_is_paused = True` (with lock), publishes state 'paused', calls handler
  - **RESUME**: Sets `_is_paused = False` (with lock), publishes state 'idle', calls handler
  - **CANCEL**: Uses `run_manager.complete_run()` to clear active run_id, publishes state 'idle', calls handler
- **State Updates**: Publishes machine state to KV store for all built-in commands
- **Error Handling**: Publishes error responses even after ack (since ack already sent)

### Keep-Alive Mechanism
- **Background Task**: Runs independently during handler execution
- **Timer Reset**: Calls `msg.in_progress()` every 25 seconds
- **Auto-Cleanup**: Task is cancelled when handler completes

### Response Publishing
- **Stream Selection**: 
  - Queue commands → `RESPONSE_QUEUE` stream
  - Immediate commands → `RESPONSE_IMMEDIATE` stream
- **Message Transformation**: Converts original message header to RESPONSE type
- **Timestamp**: Adds current timestamp to response header

### Run Management
- **RunManager**: Thread-safe run state management
  - Tracks `active_run_id` for the machine
  - `start_run(run_id)`: Sets active run_id (fails if another run is active)
  - `complete_run(run_id)`: Clears active run_id (fails if run_id doesn't match)
  - `validate_run_id(run_id)`: Checks if run_id matches active run_id
  - `get_active_run_id()`: Returns current active run_id
- **Run Lifecycle**: 
  - START command sets active run_id
  - Queue commands must match active run_id
  - COMPLETE or CANCEL command clears active run_id

