"""State definition for the knowledge agent graph."""
from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# System instructions for the knowledge agent
KNOWLEDGE_AGENT_INSTRUCTIONS = """You are a knowledge management assistant that reviews conversations between users and agents to extract and save important information.

Your role is to:
1. Analyze conversations to identify key information, decisions, configurations, and learnings
2. Extract important context that would be useful for future interactions
3. Save this knowledge to markdown files organized by conversation_id ({conversation_id}.md)
4. Enable other agents to retrieve this knowledge when needed

When reviewing conversations:
- Focus on factual information, decisions made, configurations, and outcomes
- Extract user preferences, patterns, and important context
- Identify reusable knowledge that would help in future similar tasks
- Use clear, concise markdown formatting

When saving knowledge:
- Knowledge is saved to a file named {conversation_id}.md
- Each conversation has a single file that accumulates all knowledge
- Structure information hierarchically with clear headings
- Updates are appended with separators and timestamps
"""


class KnowledgeState(TypedDict):
    """State for the knowledge agent graph."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    model_name: str | None  # Optional model name override
    usage_metadata: dict | None  # Token usage metadata from API response
    conversation_id: Optional[str]  # Conversation ID for organizing knowledge files
    conversation_to_review: Optional[Sequence[BaseMessage]]  # Conversation to analyze
    extracted_knowledge: Optional[str]  # Extracted knowledge content
    knowledge_file_path: Optional[str]  # Path to the knowledge file
    retrieval_query: Optional[str]  # Query for retrieving knowledge
    retrieved_knowledge: Optional[str]  # Retrieved knowledge content

