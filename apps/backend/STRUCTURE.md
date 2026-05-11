# Backend Application Structure

This application follows a multi-agent architecture pattern:

```
apps/backend/
├── app/
│   ├── main.py                  # FastAPI application entry point
│   ├── routers/                 # API routes
│   │   ├── agents.py            # Agent API endpoints
│   │   ├── items.py             # Example items endpoints
│   │   └── models.py            # Pydantic models
│   ├── agents/                  # LangGraph agents
│   │   ├── researcher/          # Research agent
│   │   │   ├── agent.py         # Graph definition
│   │   │   ├── state.py         # State schema
│   │   │   ├── nodes.py         # Node functions
│   │   │   └── tools.py         # Agent-specific tools
│   │   └── general/             # General/router
│   │       ├── router.py        # Routing logic
│   │       ├── workflow.py      # Main general graph
│   │       └── state.py         # General state
│   ├── services/                # Business services
│   │   └── openrouter/          # OpenRouter LLM service
│   ├── dependencies.py          # FastAPI dependencies
│   └── internal/                # Internal routes (admin, etc.)
├── langgraph.json               # LangGraph configuration
└── pyproject.toml               # Dependencies
```

## Key Components

### General Agent
The `general` agent is the main entry point that routes requests to appropriate agents:
- **router.py**: Contains logic to decide which agent should handle a request
- **workflow.py**: Defines the main graph that orchestrates all agents
- Routes to `researcher` based on the request type

### Researcher Agent
Your current research agent, specialized in:
- Gathering information
- Analyzing research findings
- Presenting structured results

## Usage

The `langgraph.json` configuration exposes two graphs:
- `general`: Main general agent (use this for most cases)
- `researcher`: Direct access to research agent

## Adding New Agents

1. Create a new directory under `app/agents/`
2. Add `instructions.md`, `agent.py`, `state.py`, `nodes.py`, and `tools.py`
3. Update `general/workflow.py` to include the new agent
4. Update `langgraph.json` to expose the new graph

