"""Knowledge agent graph definition."""
import sys
from pathlib import Path
from langgraph.graph import StateGraph, END
from app.agents.knowledge.state import KnowledgeState
from app.agents.knowledge.nodes import knowledge_review_and_save_node

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def create_knowledge_graph():
    """Create and compile the knowledge agent graph.
    
    The graph has a single entry point "review_and_save" which:
    1. Reviews the conversation
    2. Extracts knowledge
    3. Saves it to {conversation_id}.md
    
    The "retrieve" operation is handled directly by the router endpoint
    and doesn't go through this graph.
    """
    workflow = StateGraph(KnowledgeState)
    
    # Add the main node that reviews and saves knowledge
    workflow.add_node("review_and_save", knowledge_review_and_save_node)
    
    # Set entry point - this is the start node
    workflow.set_entry_point("review_and_save")
    
    # Flow: review_and_save -> end
    workflow.add_edge("review_and_save", END)
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_knowledge_graph()

