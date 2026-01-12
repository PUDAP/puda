import asyncio
from typing import List
import uuid
from fastapi import APIRouter, HTTPException
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from app.agents.researcher.agent import graph as researcher_graph
from app.agents.researcher.state import RESEARCHER_INSTRUCTIONS
from app.models import AgentRequest, AgentResponse, UsageMetadata

router = APIRouter(
    prefix="/v1/agents",
    tags=["research"],
    responses={500: {"description": "Internal server error"}},
)


@router.post("/research")
async def research(request: AgentRequest) -> AgentResponse:
    """
    Perform research on a given query using the researcher agent.
    
    Args:
        request: Research request containing query, optional model_name, and verbose flag
        
    Returns:
        AgentResponse with result, sources, and usage metadata
    """
    try:
        # Generate or use provided conversation ID
        conversation_id = request.conversation_id or str(uuid.uuid4())
        
        # Build message history: start with system message if new conversation
        messages: List[BaseMessage] = []
        
        # Check if we have previous message history
        if request.message_history:
            # Use messages directly from history (they're already BaseMessage instances)
            messages.extend(request.message_history)
        else:
            # New conversation: start with system message
            messages.append(SystemMessage(content=RESEARCHER_INSTRUCTIONS))
        
        # Add the new user query
        messages.append(HumanMessage(content=request.query))
        
        # Prepare initial state with full conversation history
        initial_state = { 
            "messages": messages,
            "model_name": request.model_name,
            "usage_metadata": None
        }
        
        # Invoke the researcher graph in a thread pool to avoid blocking the async event loop
        # This handles AI latency without blocking the server
        result_state = await asyncio.to_thread(researcher_graph.invoke, initial_state)
        
        # Extract the result from the state
        # The researcher graph returns messages with the AI response
        messages = result_state.get("messages", [])
        usage_metadata_dict = result_state.get("usage_metadata")
        
        # Get the final result from the last AI message
        if messages:
            last_message = messages[-1]
            result_text = last_message.content if hasattr(last_message, 'content') else str(last_message)
        else:
            result_text = "No result generated"
        
        # Extract verbose logs if requested
        if request.verbose:
            # Include the full state or message history in verbose mode
            verbose_info = {
                "messages": [
                    {
                        "type": msg.__class__.__name__,
                        "content": msg.content if hasattr(msg, 'content') else str(msg)
                    }
                    for msg in messages
                ],
                "usage_metadata": usage_metadata_dict
            }
            # Append verbose info to result
            result_text = f"{result_text}\n\n[Verbose Mode]\n{verbose_info}"
        
        # Stub sources - in a real implementation, these would be extracted from the research
        # For now, return empty list as the current implementation doesn't extract sources
        sources: List[str] = []
        
        # Extract usage metadata from state (set by the research node)
        # Pass all metadata fields, not just the three common ones
        if usage_metadata_dict:
            usage_metadata = UsageMetadata(**usage_metadata_dict)
        else:
            usage_metadata = UsageMetadata()
        
        # Prepare message history for client to store (excluding system message for privacy)
        # Return messages directly (excluding system message)
        message_history = [
            msg for msg in messages
            if not isinstance(msg, SystemMessage)  # Exclude system message from history
        ]
        
        return AgentResponse(
            result=result_text,
            sources=sources,
            usage_metadata=usage_metadata,
            conversation_id=conversation_id,
            message_history=message_history
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

