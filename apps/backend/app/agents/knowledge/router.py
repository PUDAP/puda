"""API router for the knowledge agent."""
import asyncio
from typing import List, Optional
import uuid
from fastapi import APIRouter, HTTPException
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from app.agents.knowledge.agent import graph as knowledge_graph
from app.agents.knowledge.state import KNOWLEDGE_AGENT_INSTRUCTIONS
from app.agents.knowledge.nodes import retrieve_knowledge_node
from app.models import ChatRequest, ChatResponse, UsageMetadata

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    responses={500: {"description": "Internal server error"}},
)


@router.post("/review")
async def review_and_save_knowledge(
    request: ChatRequest,
    conversation_to_review: Optional[List[BaseMessage]] = None
) -> ChatResponse:
    """
    Review a conversation and save important knowledge to markdown files.
    
    Args:
        request: Request containing query (optional), optional model_name, and verbose flag
        conversation_to_review: Optional conversation messages to review. If not provided,
                               uses message_history from request
        
    Returns:
        ChatResponse with result, knowledge file path, and usage metadata
    """
    try:
        # Use thread_id from request
        thread_id = request.thread_id
        
        # Determine conversation to review
        if conversation_to_review:
            conversation = conversation_to_review
        else:
            # Use message as a simple instruction
            conversation = [HumanMessage(content=request.message or "Review recent conversation")]
        
        # Build messages for the knowledge agent
        messages: List[BaseMessage] = []
        messages.append(SystemMessage(content=KNOWLEDGE_AGENT_INSTRUCTIONS))
        
        # Add conversation to review
        if conversation:
            messages.extend(conversation)
        
        # Add instruction to review and save
        if request.message:
            messages.append(HumanMessage(content=request.message))
        else:
            messages.append(HumanMessage(content="Review the conversation above and extract important knowledge to save."))
        
        # Prepare config for graph invocation
        config = {"configurable": {"thread_id": thread_id}}
        
        # Prepare initial state
        initial_state = {
            "messages": messages,
            "model_name": request.model_name,
            "usage_metadata": None,
            "conversation_id": thread_id,
            "conversation_to_review": conversation,
            "extracted_knowledge": None,
            "knowledge_file_path": None,
            "retrieval_query": None,
            "retrieved_knowledge": None
        }
        
        # Invoke the knowledge graph
        result_state = await knowledge_graph.ainvoke(initial_state, config=config)
        
        # Extract results
        messages = result_state.get("messages", [])
        usage_metadata_dict = result_state.get("usage_metadata")
        extracted_knowledge = result_state.get("extracted_knowledge", "")
        knowledge_file_path = result_state.get("knowledge_file_path", "")
        
        # Get the final result
        if messages:
            last_message = messages[-1]
            result_text = last_message.content if hasattr(last_message, 'content') else str(last_message)
        else:
            result_text = "Knowledge review completed."
        
        # Add file path info
        if knowledge_file_path:
            result_text = f"{result_text}\n\nKnowledge saved to: {knowledge_file_path}"
        
        # Extract usage metadata
        if usage_metadata_dict:
            usage_metadata = UsageMetadata(**usage_metadata_dict)
        else:
            usage_metadata = UsageMetadata()
        
        return ChatResponse(
            result=result_text,
            sources=[knowledge_file_path] if knowledge_file_path else [],
            usage_metadata=usage_metadata,
            thread_id=thread_id
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reviewing and saving knowledge: {str(e)}"
        ) from e


@router.post("/retrieve")
async def retrieve_knowledge(request: ChatRequest) -> ChatResponse:
    """
    Retrieve knowledge from markdown files based on conversation_id or query.
    
    Args:
        request: Request containing conversation_id (to read specific file) or 
                query (to search), optional model_name, and verbose flag
        
    Returns:
        ChatResponse with retrieved knowledge and usage metadata
    """
    try:
        # Use thread_id from request
        thread_id = request.thread_id
        
        # Build messages for the knowledge agent
        messages: List[BaseMessage] = []
        messages.append(SystemMessage(content=KNOWLEDGE_AGENT_INSTRUCTIONS))
        
        # Use message for retrieval query
        if request.message:
            messages.append(HumanMessage(content=f"Retrieve knowledge for: {request.message}"))
        else:
            messages.append(HumanMessage(content=f"Retrieve knowledge for thread_id: {thread_id}"))
        
        # Prepare config for graph invocation
        config = {"configurable": {"thread_id": thread_id}}
        
        # Prepare initial state
        initial_state = {
            "messages": messages,
            "model_name": request.model_name,
            "usage_metadata": None,
            "conversation_id": thread_id,
            "conversation_to_review": None,
            "extracted_knowledge": None,
            "knowledge_file_path": None,
            "retrieval_query": request.message,
            "retrieved_knowledge": None
        }
        
        # Invoke the knowledge graph's retrieve node
        result_state = retrieve_knowledge_node(initial_state)
        
        # Extract results
        retrieved_knowledge = result_state.get("retrieved_knowledge", "No knowledge found")
        
        # Extract usage metadata (if any)
        usage_metadata_dict = result_state.get("usage_metadata")
        if usage_metadata_dict:
            usage_metadata = UsageMetadata(**usage_metadata_dict)
        else:
            usage_metadata = UsageMetadata()
        
        return ChatResponse(
            result=retrieved_knowledge,
            sources=[],
            usage_metadata=usage_metadata,
            thread_id=thread_id
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving knowledge: {str(e)}"
        ) from e

