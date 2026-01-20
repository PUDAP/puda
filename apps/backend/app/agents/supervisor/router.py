"""API router for the supervisor agent."""
import asyncio
from typing import List
import uuid
from fastapi import APIRouter, HTTPException
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from app.agents.supervisor.agent import graph as supervisor_graph
from app.agents.supervisor.state import SUPERVISOR_INSTRUCTIONS
from app.models import ChatRequest, ChatResponse, UsageMetadata

router = APIRouter(
    prefix="/supervisor",
    tags=["supervisor"],
    responses={500: {"description": "Internal server error"}},
)


@router.post("")
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Chat with the supervisor agent that coordinates specialized subagents.
    
    The supervisor maintains conversation context and decides which subagents
    to call (research, plan, hardware, context management) based on the request.
    
    Args:
        request: Request containing query, optional model_name, and verbose flag
        
    Returns:
        ChatResponse with result, sources, and usage metadata
    """
    try:
        # Use thread_id from request
        thread_id = request.thread_id
        
        # Build message history: start with system message if new conversation
        messages: List[BaseMessage] = []
        
        # New conversation: start with system message
        messages.append(SystemMessage(content=SUPERVISOR_INSTRUCTIONS))
        
        # Add the new user message
        messages.append(HumanMessage(content=request.message))
        
        # Prepare config for graph invocation
        config = {"configurable": {"thread_id": thread_id}}
        
        # Prepare initial state
        initial_state = { 
            "messages": messages,
            "model_name": request.model_name,
            "usage_metadata": None,
            "conversation_id": thread_id,
            "tool_to_call": None,
            "tool_input": None
        }
        
        # Invoke the supervisor graph
        result_state = await supervisor_graph.ainvoke(initial_state, config=config)
        
        # Extract the result from the state
        messages = result_state.get("messages", [])
        usage_metadata_dict = result_state.get("usage_metadata")
        
        # Get the final result from the last AI message
        if messages:
            last_message = messages[-1]
            result_text = last_message.content if hasattr(last_message, 'content') else str(last_message)
        else:
            result_text = "No result generated"
        
        # Stub sources
        sources: List[str] = []
        
        # Extract usage metadata
        if usage_metadata_dict:
            usage_metadata = UsageMetadata(**usage_metadata_dict)
        else:
            usage_metadata = UsageMetadata()
        
        return ChatResponse(
            result=result_text,
            sources=sources,
            usage_metadata=usage_metadata,
            thread_id=thread_id
        )
        
    except TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Request timed out: {str(e)}"
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing request: {str(e)}"
        ) from e

