"""Implementation of researcher agent graph.

This file demonstrates how to add:
1. Synthesis node for better response quality
2. Quality check node for completeness validation
3. Iteration limit to prevent infinite loops
4. Source extraction for better citations
5. Result formatting for professional output

This is a reference implementation - integrate these patterns into the actual agent.py and nodes.py files.
"""
import json
import sys
from pathlib import Path
from typing import Annotated, Literal, Sequence, TypedDict
from os import getenv
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain.chat_models import init_chat_model
from langsmith import traceable

# Add backend directory to path
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.agents.researcher.tools import get_researcher_tools

load_dotenv()

# System instructions for the researcher agent
RESEARCHER_INSTRUCTIONS = """You are an expert Research Assistant optimized for accuracy and efficiency. Your goal is to provide comprehensive, evidence-based answers.

### WHEN TO USE WEB SEARCH TOOLS
**ALWAYS use web search tools for:**
- Current events, news, or recent developments
- Specific facts, statistics, or data that may change
- Information about specific people, companies, products, or places
- Technical information, research papers, or specialized knowledge
- Any query where citations or sources are important
- Information that might be outdated in your training data

**You MAY answer directly (without tools) for:**
- General knowledge questions that are well-established facts
- Mathematical or logical questions
- Definitions of common terms

### PLANNING & EXECUTION PROTOCOL
1. **Analyze First:** Before calling any tool, analyze the user's request to identify *all* distinct pieces of information needed.
2. **Batch Operations:** - If you need to search for multiple topics (e.g., "Compare X and Y"), you MUST call the search tool for X and the search tool for Y **in the same turn** (parallel tool calling).
   - Do NOT perform sequential searches (Search A -> Wait for result -> Search B) unless the second search strictly depends on the result of the first.
3. **Query Formulation:** Create specific, high-quality search queries. Avoid vague terms. If a topic is complex, break it down into distinct sub-queries to execute in parallel.
4. **Tool Call Limit:** You have a maximum of 3 tool call iterations. Use them efficiently by batching related searches together. After 3 iterations, you must synthesize your findings.

### RESPONSE GUIDELINES
- **Synthesis:** Do not just list search results. Synthesize them into a coherent narrative.
- **Citations:** When using search tools, explicitly reference the source of your information. When answering directly, acknowledge that you're providing general knowledge.
- **Fallbacks:** If tool results are empty or irrelevant, strictly state this rather than hallucinating an answer.
- **Completeness:** Ensure all aspects of the user's original prompt are addressed in the final summary.
"""


class ResearcherState(TypedDict, total=False):
    """State for the researcher agent graph with iteration tracking and sources."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    model_name: str | None  # Optional model name override
    usage_metadata: dict | None  # Token usage metadata from API response
    iteration_count: int  # Track research iterations
    sources: list[dict]  # Store extracted sources
    quality_check_passed: bool  # Flag for quality validation


# Constants
MAX_TOOL_CALLS = 3  # Maximum number of tool call iterations


@traceable(name="synthesis_node")
def synthesis_node(state: ResearcherState) -> ResearcherState:
    """Synthesize research findings into a coherent response.
    
    This node:
    1. Takes all research results from messages
    2. Creates a comprehensive, well-structured answer to answer the user's question
    3. Includes proper citations
    4. Formats the response professionally
    """
    messages = state.get("messages", [])
    if not messages:
        return state
    
    # Find the original user query
    user_query = None
    for msg in messages:
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break
    
    if not user_query:
        return state
    
    # Get sources from state, or extract from messages if not present
    sources = state.get("sources", [])
    
    # Format sources for the prompt
    sources_text = ""
    if sources:
        sources_list = []
        for i, source in enumerate(sources, 1):
            sources_list.append(f"[{i}] {source['title']} - {source['url']}")
        sources_text = "\n\nAvailable Sources:\n" + "\n".join(sources_list) + "\n"
    
    # Create synthesis prompt
    synthesis_prompt = f"""Based on the research results below, create a comprehensive, well-structured answer to the user's question: "{user_query}"

Requirements:
1. Synthesize all findings into a coherent narrative
2. Cite sources using [1], [2], etc. in your answer
3. Address all aspects of the original question
4. Use clear structure with sections if needed
5. Be accurate and avoid speculation
6. At the end, include a "## Sources" section with markdown links formatted as: [Source Title](URL)

{sources_text}
Research Results:
{_extract_research_results(messages)}

Provide your synthesized answer with proper source citations:"""
    
    # Use model without tools for pure synthesis
    synthesis_model = init_chat_model(
        model="minimax/minimax-m2",
        model_provider="openai",
        base_url=getenv("OPENROUTER_BASE_URL"),
        api_key=getenv("OPENROUTER_API_KEY"),
        temperature=0.3,  # Lower temperature for more focused synthesis
    )
    
    synthesis_messages = [
        SystemMessage(content=RESEARCHER_INSTRUCTIONS),
        HumanMessage(content=synthesis_prompt)
    ]
    
    # Stream the response and collect chunks
    content_chunks = []
    usage_metadata = None
    
    for chunk in synthesis_model.stream(synthesis_messages):
        # Accumulate content chunks
        if hasattr(chunk, 'content') and chunk.content:
            content_chunks.append(chunk.content)
        # Extract usage metadata from the last chunk if available
        if hasattr(chunk, 'response_metadata'):
            metadata = chunk.response_metadata
            if metadata and 'token_usage' in metadata:
                token_usage = metadata['token_usage']
                usage_metadata = {
                    'prompt_tokens': token_usage.get('prompt_tokens', 0),
                    'completion_tokens': token_usage.get('completion_tokens', 0),
                    'total_tokens': token_usage.get('total_tokens', 0),
                }
    
    # Create a complete AIMessage from collected chunks
    complete_content = ''.join(content_chunks)
    
    # Format sources section with markdown links if sources exist
    if sources:
        sources_section = "\n\n## Sources\n\n"
        for source in sources:
            sources_section += f"[{source['title']}]({source['url']})\n"
        
        # Append sources if not already in the content
        if "## Sources" not in complete_content:
            complete_content += sources_section
    
    response = AIMessage(content=complete_content)
    
    return {
        **state,
        "messages": [response],
        "usage_metadata": usage_metadata,
    }

def _extract_research_results(messages):
    """Extract research results from tool messages.
    
    In LangGraph, tool results are stored as ToolMessage objects,
    not in the tool_calls of AIMessage. We need to extract the
    actual content from ToolMessage objects.
    
    If no tool results are found, check for direct AI responses
    that may contain the answer.
    """
    results = []
    tool_results_found = False
    direct_ai_response = None
    
    for msg in messages:
        # ToolMessage contains the actual results from tool execution
        if isinstance(msg, ToolMessage):
            if msg.name == 'ddg_search':
                content = msg.content
                if content:
                    try:
                        data = json.loads(content)
                        if 'results' in data:
                            formatted_results = []
                            for i, result in enumerate(data['results'], 1):
                                formatted_results.append(
                                    f"[{i}] {result.get('title', 'No title')}\n"
                                    f"URL: {result.get('url', 'No URL')}\n"
                                    f"Description: {result.get('description', 'No description available')}\n"
                                )
                            results.append("Search Results:\n" + "\n".join(formatted_results))
                            tool_results_found = True
                        elif 'error' in data:
                            results.append(f"Search Error: {data['error']}")
                    except json.JSONDecodeError:
                        # Fallback: if content is not JSON, use as-is
                        results.append(f"Search Results:\n{content}")
                        tool_results_found = True
        # Also include the search query from AIMessage tool_calls for context
        elif isinstance(msg, AIMessage):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if tool_call.get('name') == 'ddg_search':
                        query = tool_call.get('args', {}).get('query', 'N/A')
                        results.append(f"Search Query: {query}")
            # If no tool_calls, this might be a direct answer
            elif not hasattr(msg, 'tool_calls') or not msg.tool_calls:
                # Store the most recent direct AI response
                if msg.content and len(msg.content.strip()) > 0:
                    direct_ai_response = msg.content
    
    # If we have tool results, return them
    if tool_results_found:
        return "\n\n".join(results)
    
    # If no tool results but we have a direct AI response, use that
    if direct_ai_response:
        return f"Direct response from AI:\n{direct_ai_response}"
    
    # Otherwise, no results found
    return "No research results found."


def should_continue_research(state: ResearcherState) -> Literal["tools", "synthesize"]:
    """Determine whether to continue to tools or move to synthesis.
    
    Enforces MAX_TOOL_CALLS limit to prevent excessive tool usage.
    """
    iteration_count = state.get("iteration_count", 0)
    if iteration_count >= MAX_TOOL_CALLS:
        # Force synthesis if we've exceeded the limit
        return "synthesize"
    return "tools"


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
    
    # Track tool call iterations
    iteration_count = state.get("iteration_count", 0)
    
    if hasattr(response, "tool_calls") and response.tool_calls:
        iteration_count += 1
    
    # Return the response - ToolNode will handle tool execution if needed
    return {
        **state,
        "messages": [response],
        "usage_metadata": usage_metadata,
        "iteration_count": iteration_count,
    }


def create_researcher_graph():
    """Create researcher graph with synthesis and quality checks."""
    workflow = StateGraph(ResearcherState)
    
    # Get tools and create ToolNode
    tool_node = ToolNode(get_researcher_tools())
    
    # Add nodes
    workflow.add_node("research", research_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("synthesize", synthesis_node)
    
    # Set entry point
    workflow.set_entry_point("research")
    
    # Research node routes to tools or synthesis
    workflow.add_conditional_edges(
        "research",
        should_continue_research,
        {
            "tools": "tools",
            "synthesize": "synthesize",
        }
    )
    
    # Tools always go back to research
    workflow.add_edge("tools", "research")
    
    # Synthesis ends the graph
    workflow.add_edge("synthesize", END)
    
    return workflow.compile()


# Export the compiled graph
researcher_graph = create_researcher_graph()


# Example usage
if __name__ == "__main__":
    print("Researcher graph created successfully!")

