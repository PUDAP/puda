"""Node functions for the researcher agent graph."""
import sys
from pathlib import Path
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.agents.researcher.state import ResearcherState
from app.services.openrouter import get_client, get_default_model  # noqa: E402

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def research_node(state: ResearcherState) -> ResearcherState:
    """Research node that performs research tasks."""
    # Get messages from state
    messages = state.get("messages", [])
    if not messages:
        return state
    
    # Get OpenRouter client from service
    openrouter_client = get_client()
    
    # Get model name from state if provided, otherwise use service default
    model_name = state.get("model_name") or get_default_model()
    
    # Convert LangChain messages to OpenRouter format
    # Messages are already in order (system, user, assistant, user, ...)
    openrouter_messages = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            openrouter_messages.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            openrouter_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            openrouter_messages.append({"role": "assistant", "content": msg.content})
        else:
            # Fallback for unknown message types
            content = msg.content if hasattr(msg, 'content') else str(msg)
            openrouter_messages.append({"role": "user", "content": content})
    
    # Call the OpenRouter API
    response = openrouter_client.chat.send(
        model=model_name,
        messages=openrouter_messages,
        temperature=0.7
    )
    
    # Extract the response content
    response_content = response.choices[0].message.content if response.choices else "No response generated"
    
    # Extract all usage metadata from the response
    # OpenRouter responses typically have a 'usage' field with token counts and other metadata
    usage_metadata = None
    if hasattr(response, 'usage') and response.usage:
        if hasattr(response.usage, 'model_dump'):
            # If it's a Pydantic BaseModel (v2), use model_dump() to convert to dict
            usage_metadata = response.usage.model_dump()
        elif hasattr(response.usage, 'dict'):
            # If it's a Pydantic BaseModel (v1), use dict() method
            usage_metadata = response.usage.dict()
        elif isinstance(response.usage, dict):
            # If it's already a dict, use it directly
            usage_metadata = response.usage.copy()
        else:
            # If it's a regular object, convert all attributes to a dict
            usage_metadata = {
                key: getattr(response.usage, key)
                for key in dir(response.usage)
                if not key.startswith('_') and not callable(getattr(response.usage, key, None))
            }
    
    # Create AIMessage for the response
    ai_message = AIMessage(content=response_content)
    
    # Return new message(s) - add_messages reducer will append them to existing messages
    return {
        **state,
        "messages": [ai_message],
        "usage_metadata": usage_metadata
    }


def analyze_node(state: ResearcherState) -> ResearcherState:
    """Analyze research results."""
    # TODO: Implement analysis logic
    return state

