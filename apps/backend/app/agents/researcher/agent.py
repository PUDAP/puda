"""Researcher agent graph definition."""
import sys
from pathlib import Path
from langgraph.graph import StateGraph, END
from app.agents.researcher.state import ResearcherState
from app.agents.researcher.nodes import research_node

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

def create_researcher_graph():
    """Create and compile the researcher agent graph."""
    workflow = StateGraph(ResearcherState)
    
    # Add nodes
    workflow.add_node("research", research_node)
    
    # Set entry point
    workflow.set_entry_point("research")
    
    # Add edges
    workflow.add_edge("research", END)
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_researcher_graph()

