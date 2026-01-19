"""Main router that aggregates all agent routers.

This router serves as a registry that includes all agent-specific routers.
The supervisor agent is the main entry point that coordinates subagents.
Individual agent routers are kept for direct access if needed.
"""
from fastapi import APIRouter
from app.agents.supervisor.router import router as supervisor_router
from app.agents.researcher.router import router as researcher_router
from app.agents.knowledge.router import router as knowledge_router

# Main router with prefix for all agent endpoints
router = APIRouter(
    prefix="/v1/agents",
    tags=["agents"],
)

# Include supervisor router (main entry point)
# The supervisor coordinates all subagents using the subagents pattern
router.include_router(supervisor_router)

# Include individual agent routers for direct access (optional)
router.include_router(researcher_router)
router.include_router(knowledge_router)

# To add a new subagent:
# 1. Create app/agents/{agent_name}/router.py with your routes
# 2. Add a tool wrapper in app/agents/supervisor/tools.py
# 3. Add tool execution node in app/agents/supervisor/nodes.py
# 4. Update supervisor agent.py to include the new tool node

