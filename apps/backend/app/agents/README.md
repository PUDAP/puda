# Agent Architecture

This directory contains all LangGraph agents following the **subagents pattern** from [LangChain](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents).

## Architecture Overview

The system uses a **supervisor agent** that coordinates specialized **subagents** by calling them as tools. This follows the LangChain subagents pattern where:
- **Supervisor** maintains conversation context and decides which subagents to call
- **Subagents** are stateless and invoked as tools
- **Results** are synthesized by the supervisor

## Structure

### Supervisor Agent
```
supervisor/
├── agent.py            # Supervisor graph definition
├── state.py            # Supervisor state schema
├── nodes.py            # Supervisor decision and tool execution nodes
├── tools.py            # Tool wrappers for subagents
├── router.py           # API router for supervisor
└── README.md           # Supervisor documentation
```

### Subagents
Each subagent is organized in its own folder:
```
{agent_name}/
├── __init__.py          # Package initialization
├── agent.py            # LangGraph graph definition
├── state.py            # State schema (TypedDict)
├── nodes.py            # Node functions for the graph
├── router.py           # FastAPI router (optional, for direct access)
└── tools.py            # Agent-specific tools (optional)
```

## Current Agents

### Supervisor Agent
- **Main entry point** for all agent interactions
- **Route**: `POST /v1/agents/supervisor`
- Coordinates all subagents using tool calling
- Maintains conversation context

### Subagents

1. **Researcher Agent** (`research`)
   - Research topics, find information, answer questions using RAG
   - Direct route: `POST /v1/agents/research`
   - Called via supervisor tool: `research`

2. **Planner Agent** (`plan`)
   - Break down complex operations into executable steps
   - Called via supervisor tool: `plan`

3. **Hardware Agent** (`execute_hardware`) - previously executor
   - Execute commands on hardware machines
   - Create protocols using MCP tools
   - Send commands to laboratory equipment
   - Called via supervisor tool: `execute_hardware`

4. **Context Management** (`save_context`, `retrieve_context`) - knowledge agent
   - Save important context from conversations
   - Retrieve saved knowledge
   - Direct routes: `POST /v1/agents/knowledge/review`, `/retrieve`
   - Called via supervisor tools: `save_context`, `retrieve_context`

## Adding a New Subagent

1. **Create the subagent:**
   ```bash
   mkdir -p app/agents/{agent_name}
   ```
   - Create `agent.py`, `state.py`, `nodes.py`

2. **Add tool wrapper in supervisor:**
   Edit `app/agents/supervisor/tools.py`:
   ```python
   @tool("{tool_name}", description="...")
   def call_{agent_name}_agent(input: str) -> str:
       # Invoke the subagent graph
       result = {agent_name}_graph.invoke(...)
       return result
   ```

3. **Add tool execution node:**
   Edit `app/agents/supervisor/nodes.py`:
   ```python
   def execute_{tool_name}_tool(state: SupervisorState) -> SupervisorState:
       result = call_{agent_name}_agent(state.get("tool_input"))
       return {...}
   ```

4. **Update supervisor graph:**
   Edit `app/agents/supervisor/agent.py`:
   - Add tool execution node
   - Add routing logic

5. **Update supervisor instructions:**
   Edit `app/agents/supervisor/state.py`:
   - Add tool description to `SUPERVISOR_INSTRUCTIONS`

## Router Organization

### Supervisor Router
The supervisor router is the main entry point:
- `POST /v1/agents/supervisor` - Main chat endpoint

### Individual Agent Routers
Subagents can have their own routers for direct access:
- `POST /v1/agents/research` - Direct researcher access
- `POST /v1/agents/knowledge/review` - Direct knowledge management

The main router (`app/routers/agents.py`) includes all routers.

## Benefits

1. **Centralized Control**: Supervisor maintains context and coordinates subagents
2. **Stateless Subagents**: Subagents are invoked as tools, keeping them simple
3. **Scalability**: Easy to add new subagents without modifying existing code
4. **Context Isolation**: Each subagent invocation works in a clean context
5. **Flexibility**: Can call multiple subagents in sequence or parallel

## References

- [LangChain Subagents Documentation](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
- Supervisor maintains conversation context
- Subagents are stateless and invoked as tools
- Results are synthesized by supervisor

