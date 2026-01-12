"""State definition for the executor agent graph."""
from typing import Annotated, Literal, Sequence, TypedDict, Optional, List, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ExecutorState(TypedDict):
    """State for the executor agent graph."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Discovery phase
    discovered_machines: Optional[List[Dict[str, Any]]]  # List of discovered MCP servers
    target_machine: Optional[str]  # Selected machine for execution
    
    # Planning phase
    command_plan: Optional[List[Dict[str, Any]]]  # Generated command sequence
    plan_status: Optional[Literal["pending", "generated", "validated"]]  # Plan status
    
    # Execution phase
    execution_status: Optional[Literal["pending", "running", "completed", "failed"]]
    execution_result: Optional[Dict[str, Any]]  # Execution results
    
    # Error handling
    error: Optional[str]  # Error message if any

