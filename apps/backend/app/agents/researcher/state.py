"""State definition for the researcher agent graph."""
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# System instructions for the researcher agent
RESEARCHER_INSTRUCTIONS = """You are a helpful research assistant with access to various laboratory and research tools.

When a user asks a question:
1. For machine-specific tasks, use the appropriate MCP tools.
2. After using tools, provide a comprehensive analysis and summary of the findings
3. Always generate a meaningful response that synthesizes the tool results
4. Be informative, accurate, and helpful in your explanations
"""


class ResearcherState(TypedDict):
    """State for the researcher agent graph."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    model_name: str | None  # Optional model name override
    usage_metadata: dict | None  # Token usage metadata from API response
    # Add more state fields as needed

