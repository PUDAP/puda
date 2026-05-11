"""Router logic to decide which agent to call."""
from .state import GeneralState


def route_to_agent(state: GeneralState) -> str:
    """
    Determine which agent should handle the current request.
    
    Returns:
        "researcher" - for research tasks
        "executor" - for machine command execution tasks
        "end" - when task is complete
    """
    # TODO: Implement routing logic based on state
    # For now, simple logic based on messages
    messages = state.get("messages", [])
    
    if not messages:
        return "end"
    
    # Simple keyword-based routing (replace with LLM-based routing)
    last_message = str(messages[-1]).lower()
    
    if any(keyword in last_message for keyword in ["research", "find", "search", "lookup"]):
        return "researcher"
    elif any(keyword in last_message for keyword in ["execute", "run", "command", "machine", "mcp", "first", "pipette", "protocol"]):
        return "executor"
    
    return "end"

