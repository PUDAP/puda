"""Tools that wrap subagents for the supervisor to call."""
import sys
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from app.agents.researcher.agent import graph as researcher_graph, RESEARCHER_INSTRUCTIONS
from app.agents.knowledge.agent import graph as knowledge_graph
from app.agents.knowledge.state import KNOWLEDGE_AGENT_INSTRUCTIONS
from app.agents.knowledge.nodes import retrieve_knowledge_node
from app.agents.executor.agent import graph as executor_graph
from app.agents.executor.state import ExecutorState

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


@tool("research", description="Research a topic, find information, or answer questions using RAG and available tools. Use this for information gathering, fact-finding, or when you need to look up something.")
def call_research_agent(query: str) -> str:
    """Invoke the research agent to perform research tasks.
    
    Args:
        query: The research query or question to investigate
        
    Returns:
        The research results and findings
    """
    # Prepare state for researcher agent
    initial_state = {
        "messages": [
            SystemMessage(content=RESEARCHER_INSTRUCTIONS),
            HumanMessage(content=query)
        ],
        "model_name": None,
        "usage_metadata": None
    }
    
    # Invoke the researcher graph
    result_state = researcher_graph.invoke(initial_state)
    
    # Extract the final message content
    messages = result_state.get("messages", [])
    if messages:
        last_message = messages[-1]
        return last_message.content if hasattr(last_message, 'content') else str(last_message)
    
    return "No research results generated."


@tool("plan", description="Plan a task, break down complex operations into steps, or create execution plans. Use this when you need to organize work, sequence operations, or prepare a strategy.")
def call_planner_agent(task: str, context: Optional[str] = None) -> str:
    """Invoke the planner agent to create task plans.
    
    Args:
        task: The task or goal to plan for
        context: Optional context or constraints for planning
        
    Returns:
        The execution plan
    """
    from app.agents.planner.agent import graph as planner_graph
    from app.agents.planner.state import PLANNER_INSTRUCTIONS
    
    # Prepare state for planner agent
    plan_prompt = f"Task: {task}"
    if context:
        plan_prompt += f"\n\nContext: {context}"
    
    initial_state = {
        "messages": [
            SystemMessage(content=PLANNER_INSTRUCTIONS),
            HumanMessage(content=plan_prompt)
        ],
        "model_name": None,
        "usage_metadata": None,
        "plan": None
    }
    
    # Invoke the planner graph
    result_state = planner_graph.invoke(initial_state)
    
    # Extract the plan
    plan = result_state.get("plan", "")
    if not plan:
        messages = result_state.get("messages", [])
        if messages:
            last_message = messages[-1]
            plan = last_message.content if hasattr(last_message, 'content') else str(last_message)
    
    return plan if plan else "No plan generated."


@tool("execute_hardware", description="Execute commands on hardware machines, create machine protocols using MCP tools, or send commands to laboratory equipment. Use this for any hardware control, machine operations, or protocol execution tasks.")
def call_hardware_agent(command: str, machine: Optional[str] = None) -> str:
    """Invoke the hardware/executor agent to execute machine commands.
    
    Args:
        command: The command or protocol to execute
        machine: Optional target machine identifier
        
    Returns:
        Execution results and status
    """
    # Prepare state for executor agent
    initial_state: ExecutorState = {
        "messages": [
            HumanMessage(content=f"Execute: {command}" + (f" on {machine}" if machine else ""))
        ],
        "discovered_machines": None,
        "target_machine": machine,
        "command_plan": None,
        "plan_status": None,
        "execution_status": None,
        "execution_result": None,
        "error": None
    }
    
    # Invoke the executor graph
    result_state = executor_graph.invoke(initial_state)
    
    # Extract execution results
    execution_result = result_state.get("execution_result")
    execution_status = result_state.get("execution_status", "unknown")
    error = result_state.get("error")
    
    if error:
        return f"Execution failed: {error}"
    
    if execution_result:
        return f"Execution {execution_status}: {execution_result}"
    
    return f"Execution status: {execution_status}"


@tool("save_context", description="Save important information, context, or knowledge from the conversation to memory. Use this to remember key decisions, configurations, preferences, or important context for future reference.")
def call_knowledge_agent_save(conversation_id: str, context: Optional[str] = None) -> str:
    """Invoke the knowledge agent to save context.
    
    Args:
        conversation_id: The conversation ID to save knowledge for
        context: Optional specific context to save (if not provided, reviews full conversation)
        
    Returns:
        Confirmation of saved knowledge
    """
    # Prepare state for knowledge agent
    initial_state = {
        "messages": [
            SystemMessage(content=KNOWLEDGE_AGENT_INSTRUCTIONS),
            HumanMessage(content=context or "Review the conversation and extract important knowledge to save.")
        ],
        "model_name": None,
        "usage_metadata": None,
        "conversation_id": conversation_id,
        "conversation_to_review": None,
        "extracted_knowledge": None,
        "knowledge_file_path": None,
        "retrieval_query": None,
        "retrieved_knowledge": None
    }
    
    # Invoke the knowledge graph
    result_state = knowledge_graph.invoke(initial_state)
    
    knowledge_file_path = result_state.get("knowledge_file_path", "")
    if knowledge_file_path:
        return f"Knowledge saved to: {knowledge_file_path}"
    
    return "Knowledge saved successfully."


@tool("retrieve_context", description="Retrieve saved context, knowledge, or information from previous conversations. Use this when you need to recall past decisions, configurations, or important information that was saved.")
def call_knowledge_agent_retrieve(conversation_id: Optional[str] = None, query: Optional[str] = None) -> str:
    """Invoke the knowledge agent to retrieve context.
    
    Args:
        conversation_id: Optional conversation ID to retrieve knowledge for
        query: Optional search query to find relevant knowledge
        
    Returns:
        Retrieved knowledge content
    """
    if not conversation_id and not query:
        return "Error: Either conversation_id or query is required for retrieval."
    
    # Prepare state for knowledge retrieval
    initial_state = {
        "messages": [],
        "model_name": None,
        "usage_metadata": None,
        "conversation_id": conversation_id,
        "conversation_to_review": None,
        "extracted_knowledge": None,
        "knowledge_file_path": None,
        "retrieval_query": query,
        "retrieved_knowledge": None
    }
    
    # Invoke retrieve node
    result_state = retrieve_knowledge_node(initial_state)
    
    retrieved_knowledge = result_state.get("retrieved_knowledge", "No knowledge found.")
    return retrieved_knowledge

