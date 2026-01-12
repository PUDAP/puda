"""OpenRouter LLM service for agent interactions."""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from openrouter import OpenRouter

# Load .env file from the backend directory
_backend_root = Path(__file__).parent.parent.parent.parent
_env_file = _backend_root / ".env"
# Try loading from backend root first, then fallback to current directory
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Fallback: try loading from current directory (useful for different execution contexts)
    load_dotenv()


class OpenRouterConfig:
    """OpenRouter service configuration."""
    API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    DEFAULT_MODEL: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")


# Global OpenRouter client instance (singleton pattern)
_openrouter_client: Optional[OpenRouter] = None


def get_client() -> OpenRouter:
    """Get or create the OpenRouter client instance.
    
    Returns:
        OpenRouter client instance
        
    Raises:
        ValueError: If OPENROUTER_API_KEY is not set
    """
    global _openrouter_client  # noqa: PLW0603
    if _openrouter_client is None:
        if not OpenRouterConfig.API_KEY:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable is required. "
                f"Please set it in your .env file at {_env_file} or as an environment variable."
            )
        _openrouter_client = OpenRouter(api_key=OpenRouterConfig.API_KEY)
    return _openrouter_client


def get_default_model() -> str:
    """Get the default OpenRouter model name.
    
    Returns:
        Default model name string
    """
    return OpenRouterConfig.DEFAULT_MODEL

