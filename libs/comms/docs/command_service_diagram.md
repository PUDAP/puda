# CommandService Message Flow

This diagram shows how `CommandService` sends commands to machines via NATS and handles responses.

## Queue Command Flow

```mermaid
flowchart TD
    Start([send_queue_command<br/>called]) --> GetHandler[Get/Create ResponseHandler<br/>for machine_id]
    GetHandler --> RegisterPending[Register Pending Response<br/>key: run_id:step_number<br/>Create asyncio.Event]
    RegisterPending --> BuildPayload[Build NATSMessage<br/>with CommandRequest]
    BuildPayload --> Publish[Publish to JetStream<br/>COMMAND_QUEUE stream<br/>subject: puda.machine_id.cmd.queue]
    Publish --> WaitEvent[Wait for Event<br/>with timeout]
    
    WaitEvent --> Timeout{Timeout?}
    Timeout -->|Yes| RemovePending[Remove Pending<br/>Registration]
    RemovePending --> ReturnNone[Return None]
    ReturnNone --> End1([End])
    
    Timeout -->|No| EventSet[Event Set<br/>Response Received]
    EventSet --> Sleep[Sleep 0.1s<br/>Ensure message processed]
    Sleep --> GetResponse[Get Response<br/>from pending_responses<br/>Delete after retrieval]
    GetResponse --> ReturnResponse[Return NATSMessage]
    ReturnResponse --> End2([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End1 fill:#ffe1e1,color:#000000
    style End2 fill:#d4edda,color:#000000
    style RegisterPending fill:#fff3cd,color:#000000
    style Publish fill:#d1ecf1,color:#000000
    style WaitEvent fill:#fff3cd,color:#000000
```

## Immediate Command Flow

```mermaid
flowchart TD
    Start([send_immediate_command<br/>called]) --> GetHandler[Get/Create ResponseHandler<br/>for machine_id]
    GetHandler --> RegisterPending[Register Pending Response<br/>key: run_id:step_number<br/>Create asyncio.Event]
    RegisterPending --> BuildPayload[Build NATSMessage<br/>with CommandRequest]
    BuildPayload --> Publish[Publish to JetStream<br/>COMMAND_IMMEDIATE stream<br/>subject: puda.machine_id.cmd.immediate]
    Publish --> WaitEvent[Wait for Event<br/>with timeout]
    
    WaitEvent --> Timeout{Timeout?}
    Timeout -->|Yes| RemovePending[Remove Pending<br/>Registration]
    RemovePending --> ReturnNone[Return None]
    ReturnNone --> End1([End])
    
    Timeout -->|No| EventSet[Event Set<br/>Response Received]
    EventSet --> Sleep[Sleep 0.1s<br/>Ensure message processed]
    Sleep --> GetResponse[Get Response<br/>from pending_responses<br/>Delete after retrieval]
    GetResponse --> ReturnResponse[Return NATSMessage]
    ReturnResponse --> End2([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End1 fill:#ffe1e1,color:#000000
    style End2 fill:#d4edda,color:#000000
    style RegisterPending fill:#fff3cd,color:#000000
    style Publish fill:#d1ecf1,color:#000000
    style WaitEvent fill:#fff3cd,color:#000000
```

## Sequential Commands Flow

```mermaid
flowchart TD
    Start([send_queue_commands<br/>called with list]) --> ValidateList{List<br/>Empty?}
    ValidateList -->|Yes| ReturnNone1[Return None]
    ReturnNone1 --> End1([End])
    
    ValidateList -->|No| SendStart[Send START Command<br/>via send_immediate_command]
    SendStart --> StartTimeout{START<br/>Timeout?}
    StartTimeout -->|Yes| ReturnNone2[Return None]
    ReturnNone2 --> End2([End])
    
    StartTimeout -->|No| StartError{START<br/>Error?}
    StartError -->|Yes| ReturnStartError[Return START<br/>Error Response]
    ReturnStartError --> End3([End])
    
    StartError -->|No| LoopStart[For each command<br/>in sequence]
    LoopStart --> SendCommand[Send Queue Command<br/>via send_queue_command]
    SendCommand --> CommandResult{Command<br/>Result?}
    
    CommandResult -->|None/Timeout| ReturnNone3[Return None]
    ReturnNone3 --> End4([End])
    
    CommandResult -->|Error Status| ReturnError[Return Error<br/>Response]
    ReturnError --> End5([End])
    
    CommandResult -->|Success| StoreResponse[Store as<br/>last_response]
    StoreResponse --> MoreCommands{More<br/>Commands?}
    MoreCommands -->|Yes| LoopStart
    MoreCommands -->|No| SendComplete[Send COMPLETE Command<br/>via send_immediate_command]
    
    SendComplete --> CompleteTimeout{COMPLETE<br/>Timeout?}
    CompleteTimeout -->|Yes| ReturnNone4[Return None]
    ReturnNone4 --> End6([End])
    
    CompleteTimeout -->|No| CompleteError{COMPLETE<br/>Error?}
    CompleteError -->|Yes| ReturnCompleteError[Return COMPLETE<br/>Error Response]
    ReturnCompleteError --> End7([End])
    
    CompleteError -->|No| ReturnLast[Return last_response<br/>from sequence]
    ReturnLast --> End8([End])
    
    SendCommand --> Exception{Exception<br/>during sequence?}
    Exception -->|Yes| TryComplete[Try to send COMPLETE<br/>for cleanup]
    TryComplete --> Reraise[Re-raise Exception]
    Reraise --> End9([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End1 fill:#ffe1e1,color:#000000
    style End2 fill:#ffe1e1,color:#000000
    style End3 fill:#ffe1e1,color:#000000
    style End4 fill:#ffe1e1,color:#000000
    style End5 fill:#ffe1e1,color:#000000
    style End6 fill:#ffe1e1,color:#000000
    style End7 fill:#ffe1e1,color:#000000
    style End8 fill:#d4edda,color:#000000
    style End9 fill:#ffe1e1,color:#000000
    style SendStart fill:#d1ecf1,color:#000000
    style SendCommand fill:#d1ecf1,color:#000000
    style SendComplete fill:#d1ecf1,color:#000000
    style LoopStart fill:#fff3cd,color:#000000
```

## Response Handler Flow

```mermaid
flowchart TD
    Start([ResponseHandler<br/>Initialization]) --> SubscribeQueue[Subscribe to<br/>RESPONSE_QUEUE stream<br/>subject: puda.machine_id.cmd.response.queue]
    SubscribeQueue --> SubscribeImmediate[Subscribe to<br/>RESPONSE_IMMEDIATE stream<br/>subject: puda.machine_id.cmd.response.immediate]
    SubscribeImmediate --> Initialized[Handler Initialized<br/>Ready to receive]
    Initialized --> End1([End])
    
    MessageReceived([Message Received<br/>from Response Stream]) --> ParseJSON[Parse JSON to<br/>NATSMessage]
    ParseJSON --> ExtractFields[Extract run_id,<br/>step_number, command]
    ExtractFields --> ValidateFields{run_id and<br/>step_number<br/>present?}
    
    ValidateFields -->|No| LogError[Log Error<br/>Missing required fields]
    LogError --> Nak[msg.nak<br/>Put back in queue]
    Nak --> End2([End])
    
    ValidateFields -->|Yes| BuildKey[Build Key:<br/>run_id:step_number]
    BuildKey --> CheckPending{Key in<br/>_pending_responses?}
    
    CheckPending -->|No| LogUnmatched[Log Debug<br/>Unmatched response]
    LogUnmatched --> AckUnmatched[msg.ack<br/>Remove from queue]
    AckUnmatched --> End3([End])
    
    CheckPending -->|Yes| LogMatch[Log Info<br/>Response matched]
    LogMatch --> CheckStatus{Response<br/>Status?}
    CheckStatus -->|ERROR| LogErrorCode[Log Error<br/>Error Code & Message]
    CheckStatus -->|SUCCESS| LogSuccess[Log Info]
    
    LogErrorCode --> StoreResponse[Store NATSMessage<br/>in pending_responses]
    LogSuccess --> StoreResponse
    StoreResponse --> SetEvent[Set Event<br/>Wake waiting task]
    SetEvent --> Ack[msg.ack<br/>Acknowledge message]
    Ack --> End4([End])
    
    ParseJSON --> ParseError{Parse<br/>Error?}
    ParseError -->|Yes| LogParseError[Log Error<br/>JSON/Key/Attribute Error]
    LogParseError --> AckError[msg.ack<br/>Acknowledge anyway]
    AckError --> End5([End])
    
    style Start fill:#e1f5ff,color:#000000
    style End1 fill:#d4edda,color:#000000
    style End2 fill:#ffe1e1,color:#000000
    style End3 fill:#ffe1e1,color:#000000
    style End4 fill:#d4edda,color:#000000
    style End5 fill:#ffe1e1,color:#000000
    style SubscribeQueue fill:#d1ecf1,color:#000000
    style SubscribeImmediate fill:#d1ecf1,color:#000000
    style ValidateFields fill:#fff3cd,color:#000000
    style CheckPending fill:#fff3cd,color:#000000
    style SetEvent fill:#fff3cd,color:#000000
```

## Complete Architecture Overview

```mermaid
flowchart TB
    subgraph Client["CommandService"]
        Service[CommandService<br/>Manages connections<br/>Sends commands]
        HandlerDict[ResponseHandler Dict<br/>One per machine_id]
        
        Service --> HandlerDict
        
        subgraph Methods["Public Methods"]
            SendQueue[send_queue_command]
            SendImmediate[send_immediate_command]
            SendSequential[send_queue_commands<br/>START → commands → COMPLETE]
            StartRun[start_run]
            CompleteRun[complete_run]
        end
        
        Service --> Methods
    end
    
    subgraph Handler["ResponseHandler per Machine"]
        PendingDict[_pending_responses<br/>Dict: run_id:step_number →<br/>event, response]
        QueueSub[Queue Response<br/>Subscription]
        ImmediateSub[Immediate Response<br/>Subscription]
        
        QueueSub --> HandleMsg[_handle_message]
        ImmediateSub --> HandleMsg
        HandleMsg --> PendingDict
    end
    
    subgraph NATS["NATS JetStream"]
        CommandQueue[COMMAND_QUEUE Stream<br/>WorkQueue Retention]
        CommandImmediate[COMMAND_IMMEDIATE Stream<br/>WorkQueue Retention]
        ResponseQueue[RESPONSE_QUEUE Stream<br/>Interest Retention]
        ResponseImmediate[RESPONSE_IMMEDIATE Stream<br/>Interest Retention]
    end
    
    subgraph Machine["MachineClient"]
        MachineQueue[process_queue_cmd]
        MachineImmediate[process_immediate_cmd]
    end
    
    Methods -->|Publish| CommandQueue
    Methods -->|Publish| CommandImmediate
    CommandQueue --> MachineQueue
    CommandImmediate --> MachineImmediate
    MachineQueue -->|Publish Response| ResponseQueue
    MachineImmediate -->|Publish Response| ResponseImmediate
    ResponseQueue --> QueueSub
    ResponseImmediate --> ImmediateSub
    PendingDict -->|Event Signal| Methods
    
    style Service fill:#e1f5ff,color:#000000
    style HandlerDict fill:#fff3cd,color:#000000
    style PendingDict fill:#fff3cd,color:#000000
    style CommandQueue fill:#e1f5ff,color:#000000
    style CommandImmediate fill:#e1f5ff,color:#000000
    style ResponseQueue fill:#d4edda,color:#000000
    style ResponseImmediate fill:#d4edda,color:#000000
    style MachineQueue fill:#d1ecf1,color:#000000
    style MachineImmediate fill:#d1ecf1,color:#000000
    style HandleMsg fill:#d1ecf1,color:#000000
```

## Key Features

### CommandService
- **Connection Management**: Connects to NATS with retry logic (3 attempts, 3s timeout each)
- **Response Handler Management**: Creates and manages one ResponseHandler per machine_id
- **Command Sending**:
  - `send_queue_command`: Sends single queue command, waits for response
  - `send_immediate_command`: Sends immediate command (PAUSE, RESUME, CANCEL, START, COMPLETE)
  - `send_queue_commands`: Sends sequence with automatic START/COMPLETE wrapper
- **Helper Methods**:
  - `start_run`: Convenience method to send START command
  - `complete_run`: Convenience method to send COMPLETE command
- **Error Handling**: Handles timeouts, connection errors, and response errors gracefully
- **Signal Handlers**: Registers SIGTERM/SIGINT for graceful shutdown

### ResponseHandler
- **Per-Machine Handler**: One handler instance per machine_id
- **Dual Subscription**: Subscribes to both RESPONSE_QUEUE and RESPONSE_IMMEDIATE streams
- **Response Matching**: Matches responses to pending commands using `run_id:step_number` key
- **Event-Based Waiting**: Uses asyncio.Event to signal when responses arrive
- **Pending Response Storage**: Stores pending responses in dict with event and response
- **Cleanup**: Removes pending registrations after retrieval or timeout
- **Error Handling**: 
  - NAKs messages with missing required fields (puts back in queue)
  - ACKs unmatched responses (from previous runs/sessions)
  - ACKs parse errors (removes malformed messages)

### Sequential Command Flow
- **Automatic Lifecycle**: Automatically sends START before sequence, COMPLETE after success
- **Sequential Execution**: Sends commands one-by-one, waiting for each response
- **Early Termination**: Stops immediately on any command failure or timeout
- **Error Cleanup**: Attempts to send COMPLETE on exception (for state cleanup)
- **Return Value**: Returns failed command response, or last successful command response

### Response Flow
1. **Registration**: Command sends, registers pending response with event
2. **Publication**: Command published to JetStream stream
3. **Processing**: Machine processes command and publishes response
4. **Matching**: ResponseHandler receives response, matches to pending registration
5. **Signaling**: Event is set, waking waiting task
6. **Retrieval**: Task retrieves response and removes from pending dict

### Timeout Handling
- **Command Timeout**: Default 120 seconds, configurable per command
- **Timeout Behavior**: Removes pending registration, returns None
- **Connection Timeout**: 3 seconds per attempt, 3 attempts total

### Error Scenarios
- **Connection Failure**: Returns False from connect(), raises RuntimeError on command send
- **Response Timeout**: Returns None, removes pending registration
- **Response Error**: Returns NATSMessage with ERROR status
- **Parse Error**: ResponseHandler ACKs malformed messages, logs error
- **Unmatched Response**: ResponseHandler ACKs (likely from previous run/session)

