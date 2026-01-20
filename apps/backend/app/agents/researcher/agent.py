"""Researcher agent graph definition with state, nodes, and graph creation."""
import sys
from pathlib import Path
from typing import Annotated, Literal, Sequence, TypedDict
from os import getenv
from dotenv import load_dotenv
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage
from langchain.chat_models import init_chat_model
from langsmith import traceable

load_dotenv()

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.agents.researcher.tools import get_researcher_tools

# System instructions for the researcher agent
RESEARCHER_INSTRUCTIONS = """You are an expert Research Assistant optimized for accuracy and efficiency. Your goal is to provide comprehensive, evidence-based answers.

### PLANNING & EXECUTION PROTOCOL
1. **Analyze First:** Before calling any tool, analyze the user's request to identify *all* distinct pieces of information needed.
2. **Batch Operations:** - If you need to search for multiple topics (e.g., "Compare X and Y"), you MUST call the search tool for X and the search tool for Y **in the same turn** (parallel tool calling).
   - Do NOT perform sequential searches (Search A -> Wait for result -> Search B) unless the second search strictly depends on the result of the first.
3. **Query Formulation:** Create specific, high-quality search queries. Avoid vague terms. If a topic is complex, break it down into distinct sub-queries to execute in parallel.

### RESPONSE GUIDELINES
- **Synthesis:** Do not just list search results. Synthesize them into a coherent narrative.
- **Citations:** Explicitly reference the source of your information where possible.
- **Fallbacks:** If tool results are empty or irrelevant, strictly state this rather than hallucinating an answer.
- **Completeness:** Ensure all aspects of the user's original prompt are addressed in the final summary.

Remember: Efficiency is key. Gather all necessary data in as few steps as possible.
"""


class ResearcherState(TypedDict):
    """State for the researcher agent graph."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    model_name: str | None  # Optional model name override
    usage_metadata: dict | None  # Token usage metadata from API response
    tool_call_count: int  # Count of tool calls made
    sources: list[dict]  # List of source dictionaries


@traceable(name="research_node")
def research_node(state: ResearcherState) -> ResearcherState:
    """Research node that invokes the model with tool support.
    
    This node:
    1. Binds web search tools to the model
    2. Invokes the model with messages
    3. Returns the response (tool execution is handled by ToolNode in the graph)
    """
    # Get messages from state
    messages = state.get("messages", [])
    if not messages:
        return state
    
    # Use the specified model or default
    research_model = init_chat_model(
        model="minimax/minimax-m2",
        model_provider="openai",
        base_url=getenv("OPENROUTER_BASE_URL"),
        api_key=getenv("OPENROUTER_API_KEY"),
        temperature=0.7,
    )

    # Get available tools
    tools = get_researcher_tools()
    
    # Bind tools to the model
    model_with_tools = research_model.bind_tools(tools)
    
    # Invoke the model with messages
    # Invoking `model` will automatically infer the correct tracing context
    response = model_with_tools.invoke(messages)
    
    # Extract usage metadata from the response
    usage_metadata = None
    if hasattr(response, 'response_metadata'):
        metadata = response.response_metadata
        if metadata and 'token_usage' in metadata:
            token_usage = metadata['token_usage']
            usage_metadata = {
                'prompt_tokens': token_usage.get('prompt_tokens', 0),
                'completion_tokens': token_usage.get('completion_tokens', 0),
                'total_tokens': token_usage.get('total_tokens', 0),
            }
    
    # Return the response - ToolNode will handle tool execution if needed
    return {
        **state,
        "messages": [response],
        "usage_metadata": usage_metadata,
    }


def should_continue(state: ResearcherState) -> Literal["tools", "__end__"]:
    """Determine whether to continue to tools or end."""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "__end__"


def create_researcher_graph():
    """Create and compile the researcher agent graph."""
    workflow = StateGraph(ResearcherState)
    
    # Get tools and create ToolNode
    tool_node = ToolNode(get_researcher_tools())
    
    # Add nodes
    workflow.add_node("research", research_node)
    workflow.add_node("tools", tool_node)
    
    # Set entry point
    workflow.set_entry_point("research")
    
    # Add conditional edges from research node
    workflow.add_conditional_edges(
        "research",
        should_continue,
    )
    
    # Add edge from tools back to research
    workflow.add_edge("tools", "research")
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_researcher_graph()
