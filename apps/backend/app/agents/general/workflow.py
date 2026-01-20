"""The main general workflow graph."""
from langgraph.graph import StateGraph, END
from .state import GeneralState
from .router import route_to_agent
from ..researcher.agent import graph as researcher_graph
from ..executor.agent import graph as executor_graph


def create_general_graph():
    """Create and compile the general graph."""
    workflow = StateGraph(GeneralState)
    
    # Add subgraphs for each agent
    workflow.add_node("researcher", researcher_graph)
    workflow.add_node("executor", executor_graph)
    
    # Add router node
    def router_node(state: GeneralState) -> GeneralState:
        """Route to the appropriate agent."""
        next_agent = route_to_agent(state)
        return {**state, "next_agent": next_agent}
    
    workflow.add_node("router", router_node)
    
    # Set entry point
    workflow.set_entry_point("router")
    
    # Add conditional edges based on routing decision
    def route_condition(state: GeneralState) -> str:
        """Route based on next_agent decision."""
        next_agent = state.get("next_agent", "end")
        if next_agent in ["researcher", "executor", "end"]:
            return next_agent
        return "end"
    
    workflow.add_conditional_edges(
        "router",
        route_condition,
        {
            "researcher": "researcher",
            "executor": "executor",
            "end": END,
        }
    )
    
    # After each agent, route again to check if more work is needed
    workflow.add_edge("researcher", "router")
    workflow.add_edge("executor", "router")
    
    # Compile and return the graph
    return workflow.compile()


# Export the compiled graph
graph = create_general_graph()

