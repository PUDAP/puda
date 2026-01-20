# MachineClient Message Handling Flow

This diagram shows how `MachineClient` processes incoming messages from NATS JetStream.

## Queue Commands Flow

```mermaid
flowchart TD
    Start([Message Received<br/>from COMMAND_QUEUE stream]) --> Parse[Parse JSON to NATSMessage]
    Parse --> Extract[Extract run_id, step_number, command]
    
    Extract --> CheckCancelled{run_id in<br/>_cancelled_run_ids?}
    CheckCancelled -->|Yes| AckCancelled[msg.ack]
    AckCancelled --> ResponseCancelled[Publish Response:<br/>COMMAND_CANCELLED]
    ResponseCancelled --> End1([End])
    
    CheckCancelled -->|No| CheckPaused{_is_paused?}
    CheckPaused -->|Yes| ResponsePaused[Publish Response:<br/>MACHINE_PAUSED]
    ResponsePaused --> WaitLoop[msg.in_progress<br/>sleep 1s]
    WaitLoop --> RecheckCancelled{run_id in<br/>_cancelled_run_ids?}
    RecheckCancelled -->|Yes| AckCancelled
    RecheckCancelled -->|No| CheckPaused
    
    CheckPaused -->|No| KeepAlive[Start Keep-Alive<br/>Background Task]
    KeepAlive --> Execute[Execute Handler<br/>with _keep_message_alive]
    
    Execute --> HandlerSuccess{Handler<br/>Success?}
    HandlerSuccess -->|Exception| ExceptionHandler{Exception<br/>Type?}
    
    ExceptionHandler -->|CancelledError| AckCancelled
    ExceptionHandler -->|JSONDecodeError| TermJSON[msg.term]
    TermJSON --> ResponseJSON[Publish Response:<br/>JSON_DECODE_ERROR]
    ResponseJSON --> End2([End])
    
    ExceptionHandler -->|Other Exception| CheckCancelledInEx{run_id in<br/>_cancelled_run_ids?}
    CheckCancelledInEx -->|Yes| AckCancelled
    CheckCancelledInEx -->|No| TermError[msg.term]
    TermError --> ResponseError[Publish Response:<br/>EXECUTION_ERROR]
    ResponseError --> End3([End])
    
    HandlerSuccess -->|Success| CheckStatus{Response<br/>Status?}
    CheckStatus -->|SUCCESS| AckSuccess[msg.ack]
    CheckStatus -->|ERROR| TermSuccess[msg.term]
    
    AckSuccess --> PublishResponse[Publish Response<br/>to RESPONSE_QUEUE stream]
    TermSuccess --> PublishResponse
    PublishResponse --> End4([End])
    
    style Start fill:#e1f5ff
    style End1 fill:#ffe1e1
    style End2 fill:#ffe1e1
    style End3 fill:#ffe1e1
    style End4 fill:#d4edda
    style KeepAlive fill:#fff3cd
    style Execute fill:#d1ecf1
```

## Immediate Commands Flow

```mermaid
flowchart TD
    Start([Message Received<br/>from COMMAND_IMMEDIATE stream]) --> Parse[Parse JSON to NATSMessage]
    Parse --> AckImmediate[msg.ack<br/>Immediately]
    
    AckImmediate --> CheckCommand{Command<br/>Type?}
    
    CheckCommand -->|PAUSE| PauseLogic[Set _is_paused = True<br/>Publish State: 'paused']
    CheckCommand -->|RESUME| ResumeLogic[Set _is_paused = False<br/>Publish State: 'idle']
    CheckCommand -->|CANCEL| CancelLogic[Add run_id to<br/>_cancelled_run_ids<br/>Publish State: 'idle']
    CheckCommand -->|Other| OtherCommand[Handle Other<br/>Immediate Command]
    
    PauseLogic --> ExecuteHandler[Execute Handler]
    ResumeLogic --> ExecuteHandler
    CancelLogic --> ExecuteHandler
    OtherCommand --> ExecuteHandler
    
    ExecuteHandler --> HandlerResult{Handler<br/>Result?}
    
    HandlerResult -->|Success| PublishResponse[Publish Response<br/>to RESPONSE_IMMEDIATE stream]
    HandlerResult -->|Exception| ExceptionType{Exception<br/>Type?}
    
    ExceptionType -->|JSONDecodeError| ResponseJSON[Publish Response:<br/>JSON_DECODE_ERROR<br/>Publish State: 'error']
    ExceptionType -->|Other| ResponseError[Publish Response:<br/>EXECUTION_ERROR<br/>Publish State: 'error']
    
    ResponseJSON --> End1([End])
    ResponseError --> End1
    PublishResponse --> End2([End])
    
    style Start fill:#e1f5ff
    style End1 fill:#ffe1e1
    style End2 fill:#d4edda
    style AckImmediate fill:#fff3cd
    style ExecuteHandler fill:#d1ecf1
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
    
    style Start fill:#e1f5ff
    style End fill:#d4edda
    style InProgress fill:#fff3cd
    style Handler fill:#d1ecf1
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
    
    subgraph Client["MachineClient"]
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
        CancelledIds[_cancelled_run_ids]
        KeepAliveTask[Keep-Alive Task<br/>25s interval]
    end
    
    NATS --> Client
    Client --> State
    ResponsePub --> NATS
    
    style QueueStream fill:#e1f5ff
    style ImmediateStream fill:#e1f5ff
    style ResponseQueue fill:#d4edda
    style ResponseImmediate fill:#d4edda
    style ProcessQueue fill:#fff3cd
    style ProcessImmediate fill:#fff3cd
    style KeepAliveTask fill:#ffe1e1
```

## Key Features

### Queue Commands (`process_queue_cmd`)
- **Cancellation Check**: Before and during processing
- **Pause Support**: Blocks execution when paused, with periodic cancellation re-check
- **Keep-Alive**: Background task resets redelivery timer every 25 seconds
- **Ack/Term Logic**: 
  - `msg.ack()` on SUCCESS or CANCELLED
  - `msg.term()` on ERROR (prevents infinite redelivery)
- **Error Handling**: Handles JSON decode errors, cancellation, and execution errors separately

### Immediate Commands (`process_immediate_cmd`)
- **Immediate Ack**: Acknowledges message immediately after parsing
- **Built-in Commands**: Handles PAUSE, RESUME, CANCEL with state management
- **State Updates**: Publishes machine state to KV store for built-in commands
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

