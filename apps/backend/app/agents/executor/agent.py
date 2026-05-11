"""Executor agent graph definition."""
import sys
from pathlib import Path
from langgraph.graph import StateGraph, END
from .state import ExecutorState
from .nodes import discovery_node, planning_node, execution_node

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def create_executor_graph():
    """Create and compile the executor agent graph."""
    workflow = StateGraph(ExecutorState)
    
    # Add nodes for the execution pipeline
    workflow.add_node("discovery", discovery_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("execution", execution_node)
    
    # Set entry point
    workflow.set_entry_point("discovery")
    
    # Define the execution flow: discovery -> planning -> execution -> end
    workflow.add_edge("discovery", "planning")
    workflow.add_edge("planning", "execution")
    workflow.add_edge("execution", END)
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_executor_graph()

