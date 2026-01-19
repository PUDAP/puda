# Supervisor Agent

The supervisor agent follows the [LangChain subagents pattern](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents) to coordinate specialized subagents.

## Architecture

The supervisor maintains conversation context and decides which subagents to call based on user requests. Subagents are stateless and invoked as tools, returning results to the supervisor for synthesis.

### Key Characteristics

- **Centralized control**: All routing passes through the supervisor
- **Subagents as tools**: Subagents are invoked via tools, not direct user interaction
- **Context management**: Supervisor maintains conversation memory
- **Parallel execution**: Supervisor can invoke multiple subagents as needed

## Subagents

### 1. Research Agent
- **Tool**: `research`
- **Purpose**: Research topics, find information, answer questions using RAG
- **Use when**: User asks questions, needs information, or requires fact-finding

### 2. Planner Agent
- **Tool**: `plan`
- **Purpose**: Break down complex operations into executable steps
- **Use when**: Task needs planning, sequencing, or strategy development

### 3. Hardware Agent (Executor)
- **Tool**: `execute_hardware`
- **Purpose**: Execute commands on hardware machines, create protocols using MCP tools
- **Use when**: User wants to control machines, run protocols, or execute hardware commands

### 4. Context Management (Knowledge Agent)
- **Tools**: `save_context`, `retrieve_context`
- **Purpose**: Save and retrieve important context from conversations
- **Use when**: Need to remember decisions, configurations, or retrieve past information

## Workflow

```
User Request
    ↓
Supervisor Decision Node
    ↓
[Decides which tool to call]
    ↓
Tool Execution Node (subagent)
    ↓
Return to Supervisor
    ↓
Synthesize Results
    ↓
Response to User
```

## Implementation Details

### Supervisor Node
The supervisor node uses an LLM to:
1. Understand user requests
2. Decide which subagent tool to call
3. Synthesize results from subagents
4. Generate final responses

### Tool Execution
Each subagent is wrapped as a tool that:
- Receives input from supervisor
- Invokes the subagent's LangGraph workflow
- Returns results to supervisor
- Is stateless (no memory between calls)

### State Management
- **Supervisor state**: Maintains conversation context, tool decisions
- **Subagent state**: Ephemeral, created per invocation

## API Endpoint

```
POST /v1/agents/supervisor
```

The supervisor is the main entry point for all agent interactions. It automatically routes to appropriate subagents based on the request.

## Adding a New Subagent

1. Create the subagent in `app/agents/{agent_name}/`
2. Add a tool wrapper in `app/agents/supervisor/tools.py`
3. Add tool execution node in `app/agents/supervisor/nodes.py`
4. Update `app/agents/supervisor/agent.py` to include the new tool node
5. Update supervisor instructions to include the new tool

## References

- [LangChain Subagents Documentation](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
- Supervisor maintains context, subagents are stateless
- Tools enable subagent invocation
- Results are synthesized by supervisor

