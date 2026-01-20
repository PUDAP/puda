"""Node functions for the planner agent graph."""
import sys
from os import getenv
from dotenv import load_dotenv
from pathlib import Path
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.agents.planner.state import PlannerState, PLANNER_INSTRUCTIONS
from langchain.chat_models import init_chat_model

load_dotenv()

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def plan_node(state: PlannerState) -> PlannerState:
    """Plan node that creates execution plans."""
    messages = state.get("messages", [])
    if not messages:
        return state
    
    # Use LangChain chat model
    model_name = state.get("model_name") or "openai/gpt-4o-mini"
    planner_model = init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=getenv("OPENAI_API_KEY"),
        temperature=0.7,
    )
    
    # Invoke the model with LangChain messages
    response = planner_model.invoke(messages)
    
    # Extract the response content
    response_content = response.content if hasattr(response, 'content') else str(response)
    
    # Extract usage metadata from LangChain response
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
    
    # Create AIMessage for the response
    ai_message = AIMessage(content=response_content)
    
    return {
        **state,
        "messages": [ai_message],
        "plan": response_content,
        "usage_metadata": usage_metadata
    }

