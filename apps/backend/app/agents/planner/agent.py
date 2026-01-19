"""Planner agent graph definition."""
import sys
from pathlib import Path
from langgraph.graph import StateGraph, END
from app.agents.planner.state import PlannerState
from app.agents.planner.nodes import plan_node

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def create_planner_graph():
    """Create and compile the planner agent graph."""
    workflow = StateGraph(PlannerState)
    
    # Add nodes
    workflow.add_node("plan", plan_node)
    
    # Set entry point
    workflow.set_entry_point("plan")
    
    # Add edges
    workflow.add_edge("plan", END)
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_planner_graph()

