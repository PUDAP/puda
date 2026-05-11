"""Supervisor agent graph definition following the subagents pattern.

The supervisor coordinates specialized subagents by calling them as tools.
This follows the LangChain subagents architecture where:
- Supervisor maintains conversation context
- Subagents are stateless and invoked as tools
- Supervisor decides which subagent to call and synthesizes results
"""
import sys
from pathlib import Path
from langgraph.graph import StateGraph, END
from app.agents.supervisor.state import SupervisorState
from app.agents.supervisor.nodes import (
    supervisor_decision_node,
    execute_research_tool,
    execute_plan_tool,
    execute_hardware_tool,
    execute_save_context_tool,
    execute_retrieve_context_tool
)

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def create_supervisor_graph():
    """Create and compile the supervisor agent graph."""
    workflow = StateGraph(SupervisorState)
    
    # Add nodes
    workflow.add_node("supervisor", supervisor_decision_node)
    workflow.add_node("research", execute_research_tool)
    workflow.add_node("plan", execute_plan_tool)
    workflow.add_node("hardware", execute_hardware_tool)
    workflow.add_node("save_context", execute_save_context_tool)
    workflow.add_node("retrieve_context", execute_retrieve_context_tool)
    
    # Set entry point
    workflow.set_entry_point("supervisor")
    
    # Conditional routing: if tool_to_call is set, route to that tool, otherwise end
    def route_after_decision(state: SupervisorState) -> str:
        """Route based on supervisor's decision."""
        tool_to_call = state.get("tool_to_call")
        if tool_to_call:
            # Map tool names to node names
            tool_node_map = {
                "research": "research",
                "plan": "plan",
                "execute_hardware": "hardware",
                "save_context": "save_context",
                "retrieve_context": "retrieve_context"
            }
            return tool_node_map.get(tool_to_call, "supervisor")
        return "end"
    
    workflow.add_conditional_edges(
        "supervisor",
        route_after_decision,
        {
            "research": "research",
            "plan": "plan",
            "hardware": "hardware",
            "save_context": "save_context",
            "retrieve_context": "retrieve_context",
            "end": END
        }
    )
    
    # After tool execution, return to supervisor to synthesize results
    workflow.add_edge("research", "supervisor")
    workflow.add_edge("plan", "supervisor")
    workflow.add_edge("hardware", "supervisor")
    workflow.add_edge("save_context", "supervisor")
    workflow.add_edge("retrieve_context", "supervisor")
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_supervisor_graph()

