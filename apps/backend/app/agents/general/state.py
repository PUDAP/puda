"""State definition for the general graph."""
from typing import Annotated, Literal, Sequence, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GeneralState(TypedDict):
    """State for the general graph."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    next_agent: Literal["researcher", "executor", "end"] | None
    research_results: list[str] | None
    commands: list[str] | None
    # Add more state fields as needed

