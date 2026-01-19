"""Chat-related Pydantic models."""
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class UsageMetadata(BaseModel):
    """Token usage metadata and any additional metadata from the API response."""
    model_config = ConfigDict(extra='allow')  # Allow additional fields
    
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ChatRequest(BaseModel):
    """Request model for chat endpoints."""
    message: str
    thread_id: str
    model_name: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for chat endpoints."""
    result: str
    sources: List[str]
    usage_metadata: UsageMetadata
    thread_id: str  # Return thread_id for continued chatting


