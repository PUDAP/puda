"""State definition for the planner agent graph."""
from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# System instructions for the planner agent
PLANNER_INSTRUCTIONS = """You are a task planning assistant that breaks down complex operations into executable steps.

Your role is to:
1. Analyze tasks and goals
2. Break them down into sequential or parallel steps
3. Identify dependencies between steps
4. Create detailed execution plans
5. Consider constraints and requirements

When creating plans:
- Be specific and actionable
- Consider dependencies and ordering
- Identify potential issues or risks
- Provide clear step-by-step instructions
- Include validation or checkpoints where appropriate
"""


class PlannerState(TypedDict):
    """State for the planner agent graph."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    model_name: str | None  # Optional model name override
    usage_metadata: dict | None  # Token usage metadata from API response
    plan: Optional[str]  # Generated plan

