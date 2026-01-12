"""Agent-related Pydantic models."""
from typing import Optional, List, Sequence
from pydantic import BaseModel, ConfigDict
from langchain_core.messages import BaseMessage

from typing import Optional, Dict
from datetime import datetime, UTC
from pydantic import BaseModel, Field, field_validator
from app.domain.models.memory import Memory
import uuid

class Agent(BaseModel):
    """
    Agent aggregate root that manages the lifecycle and state of an AI agent
    Including its execution context, memory, and current plan
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    memories: Dict[str, Memory] = Field(default_factory=dict)
    model_name: str = Field(default="")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=2000)
    
    # Context related fields
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # Creation timestamp
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # Last update timestamp

    @field_validator("temperature")
    def validate_temperature(cls, v: float) -> float:
        """Validate temperature is between 0 and 1"""
        if not 0 <= v <= 1:
            raise ValueError("Temperature must be between 0 and 1")
        return v

    @field_validator("max_tokens")
    def validate_max_tokens(cls, v: Optional[int]) -> Optional[int]:
        """Validate max_tokens is positive if provided"""
        if v is not None and v <= 0:
            raise ValueError("Max tokens must be positive")
        return v

    class Config:
        arbitrary_types_allowed = True


class UsageMetadata(BaseModel):
    """Token usage metadata and any additional metadata from the API response."""
    model_config = ConfigDict(extra='allow')  # Allow additional fields
    
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class AgentRequest(BaseModel):
    """Base request model for agent endpoints."""
    query: str
    model_name: Optional[str] = None
    verbose: bool = False
    conversation_id: Optional[str] = None  # Optional conversation ID for maintaining context
    message_history: Optional[Sequence[BaseMessage]] = None  # Optional previous messages for context


class AgentResponse(BaseModel):
    """Base response model for agent endpoints."""
    result: str
    sources: List[str]
    usage_metadata: UsageMetadata
    conversation_id: Optional[str] = None  # Return conversation ID for continued chatting
    message_history: Optional[Sequence[BaseMessage]] = None  # Return full message history for client to store

