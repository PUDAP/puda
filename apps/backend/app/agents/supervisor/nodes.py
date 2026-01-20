"""Node functions for the supervisor agent graph."""
import sys
from os import getenv
from dotenv import load_dotenv
from pathlib import Path
from typing import Literal
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.agents.supervisor.state import SupervisorState, SUPERVISOR_INSTRUCTIONS
from app.agents.supervisor.tools import (
    call_research_agent,
    call_planner_agent,
    call_hardware_agent,
    call_knowledge_agent_save,
    call_knowledge_agent_retrieve
)
from langchain.chat_models import init_chat_model

load_dotenv()

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def supervisor_decision_node(state: SupervisorState) -> SupervisorState:
    """Supervisor node that decides which tool to call and generates response.
    
    This node uses an LLM to:
    1. Understand the user's request
    2. Decide if a subagent tool should be called
    3. Generate a response (either directly or indicating which tool to call)
    """
    messages = state.get("messages", [])
    if not messages:
        return state
    
    # Prepare messages with system instructions
    current_messages = list(messages)
    
    # Add system message with tool descriptions if not already present
    system_message_with_tools = f"""{SUPERVISOR_INSTRUCTIONS}

When you need to use a tool, respond with:
TOOL_CALL: <tool_name>
TOOL_INPUT: <input>

Available tools:
- research: For research, information gathering, or answering questions
- plan: For planning tasks or creating execution plans
- execute_hardware: For executing commands on hardware machines
- save_context: For saving important context or knowledge
- retrieve_context: For retrieving saved context or knowledge

If no tool is needed, just respond normally."""
    
    # Check if first message is a system message, update it if so
    if current_messages and isinstance(current_messages[0], SystemMessage):
        current_messages[0] = SystemMessage(content=system_message_with_tools)
    else:
        current_messages.insert(0, SystemMessage(content=system_message_with_tools))
    
    # Use LangChain chat model
    model_name = state.get("model_name") or "openai/gpt-4o-mini"
    supervisor_model = init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=getenv("OPENAI_API_KEY"),
        temperature=0.7,
    )
    
    # Invoke the model
    response = supervisor_model.invoke(current_messages)
    
    # Extract the response content
    response_content = response.content if hasattr(response, 'content') else str(response)
    
    # Parse tool call from response
    tool_to_call = None
    tool_input = None
    
    if "TOOL_CALL:" in response_content:
        lines = response_content.split("\n")
        for i, line in enumerate(lines):
            if "TOOL_CALL:" in line:
                tool_to_call = line.split("TOOL_CALL:")[1].strip()
                # Look for TOOL_INPUT on next line or same line
                if i + 1 < len(lines) and "TOOL_INPUT:" in lines[i + 1]:
                    tool_input = lines[i + 1].split("TOOL_INPUT:")[1].strip()
                break
    
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
    
    # Store decision in state
    return {
        **state,
        "messages": [AIMessage(content=response_content)],
        "tool_to_call": tool_to_call,
        "tool_input": tool_input,
        "usage_metadata": usage_metadata
    }


def execute_research_tool(state: SupervisorState) -> SupervisorState:
    """Execute the research tool."""
    tool_input = state.get("tool_input", "")
    conversation_id = state.get("conversation_id")
    
    result = call_research_agent(tool_input)
    
    # Add result as a message and return to supervisor
    return {
        **state,
        "messages": [HumanMessage(content=f"Research result: {result}")],
        "tool_to_call": None,
        "tool_input": None
    }


def execute_plan_tool(state: SupervisorState) -> SupervisorState:
    """Execute the plan tool."""
    tool_input = state.get("tool_input", "")
    
    result = call_planner_agent(tool_input)
    
    return {
        **state,
        "messages": [HumanMessage(content=f"Plan result: {result}")],
        "tool_to_call": None,
        "tool_input": None
    }


def execute_hardware_tool(state: SupervisorState) -> SupervisorState:
    """Execute the hardware tool."""
    tool_input = state.get("tool_input", "")
    
    result = call_hardware_agent(tool_input)
    
    return {
        **state,
        "messages": [HumanMessage(content=f"Hardware execution result: {result}")],
        "tool_to_call": None,
        "tool_input": None
    }


def execute_save_context_tool(state: SupervisorState) -> SupervisorState:
    """Execute the save context tool."""
    tool_input = state.get("tool_input", "")
    conversation_id = state.get("conversation_id", "default")
    
    result = call_knowledge_agent_save(conversation_id, tool_input)
    
    return {
        **state,
        "messages": [HumanMessage(content=f"Context saved: {result}")],
        "tool_to_call": None,
        "tool_input": None
    }


def execute_retrieve_context_tool(state: SupervisorState) -> SupervisorState:
    """Execute the retrieve context tool."""
    tool_input = state.get("tool_input", "")
    conversation_id = state.get("conversation_id")
    
    result = call_knowledge_agent_retrieve(conversation_id, tool_input)
    
    return {
        **state,
        "messages": [HumanMessage(content=f"Retrieved context: {result}")],
        "tool_to_call": None,
        "tool_input": None
    }
