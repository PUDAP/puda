"""API router for the researcher agent."""
from typing import List
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from app.agents.researcher.agent import graph as researcher_graph
from app.models import ChatRequest, ChatResponse, UsageMetadata

router = APIRouter(
    prefix="/research",
    tags=["research"],
    responses={500: {"description": "Internal server error"}},
)


@router.post("")
async def research(request: ChatRequest) -> ChatResponse:
    """
    Perform research on a given message using the researcher agent.
    
    LangGraph will automatically:
    - Load message history for the thread_id
    - Append the new message
    - Run the LLM
    - Save the result back to the thread
    
    Args:
        request: Research request containing message and thread_id
        
    Returns:
        ChatResponse with result, sources, and usage metadata
    """
    try:
        # 1. Just define the config with thread_id
        # LangGraph will auto-load the history for this thread_id
        config = {"configurable": {"thread_id": request.thread_id}}
        
        # 2. Pass ONLY the new user input
        # LangGraph will auto-load the history, append this new message,
        # run the LLM, and auto-save the result
        result_state = await researcher_graph.ainvoke(
            {"messages": [HumanMessage(content=request.message)]},
            config=config
        )
        
        # Extract the result from the state
        messages = result_state.get("messages", [])
        usage_metadata_dict = result_state.get("usage_metadata")
        
        # Get the final result from the last AI message
        if messages:
            last_message = messages[-1]
            result_text = last_message.content if hasattr(last_message, 'content') else str(last_message)
        else:
            result_text = "No result generated"
        
        # Stub sources - in a real implementation, these would be extracted from the research
        sources: List[str] = []
        
        # Extract usage metadata from state
        if usage_metadata_dict:
            usage_metadata = UsageMetadata(**usage_metadata_dict)
        else:
            usage_metadata = UsageMetadata()
        
        return ChatResponse(
            result=result_text,
            sources=sources,
            usage_metadata=usage_metadata,
            thread_id=request.thread_id
        )
        
    except TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Research request timed out: {str(e)}"
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error performing research: {str(e)}"
        ) from e

