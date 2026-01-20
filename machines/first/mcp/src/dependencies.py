"""
Dependencies for MCP Server

Global instances, lifespan management, and dependency injection helpers.
This follows FastAPI/Starlette conventions for dependency management.
"""

from contextlib import asynccontextmanager
from typing import Optional
import nats
from nats.js.client import JetStreamContext
from .config import Config


# 1. Container class for global singletons (avoids global statement)
class Dependencies:
    """Container for global dependency instances."""
    nats_client: Optional[nats.NATS] = None
    nats_js: Optional[JetStreamContext] = None
    nats_kv = None


# Global instance of the dependencies container
_deps = Dependencies()


# 2. Define the Lifespan Context Manager
@asynccontextmanager
async def lifespan(_app):
    """
    Manages the lifecycle of external connections.
    
    Startup: Connects to NATS.
    Shutdown: Closes all connections gracefully.
    """
    # --- STARTUP PHASE ---
    print("🚀 Starting up: Connecting to NATS...")
    
    # Connect NATS
    try:
        _deps.nats_client = await nats.connect(
            servers=Config.NATS_SERVERS,
            reconnect_time_wait=2,
            max_reconnect_attempts=-1,
        )
        
        # Initialize JetStream and Key-Value store
        _deps.nats_js = _deps.nats_client.jetstream()
        _deps.nats_kv = await _deps.nats_js.key_value(Config.KV_BUCKET_NAME)
        print("✅ NATS Connected")
    except Exception as e:
        print(f"❌ NATS Connection failed: {e}")
        # Decide here if you want to raise error and stop server startup
        raise

    # Yield control back to the application to handle requests
    yield

    # --- SHUTDOWN PHASE ---
    print("🛑 Shutting down: Closing connections...")
    
    # Close NATS
    if _deps.nats_client is not None:
        await _deps.nats_client.close()
        _deps.nats_client = None
        _deps.nats_js = None
        _deps.nats_kv = None
    print("💤 NATS Connection Closed")


# 3. Helper functions to get these dependencies in your tools
def get_nats_client() -> nats.NATS:
    """Get the NATS client instance.
    
    Returns:
        nats.NATS: The NATS client instance
        
    Raises:
        RuntimeError: If NATS client is not initialized
    """
    if _deps.nats_client is None or _deps.nats_client.is_closed:
        raise RuntimeError("NATS connection not established")
    return _deps.nats_client


def get_nats_js():
    """Get the NATS JetStream instance.
    
    Returns:
        JetStream: The JetStream instance
        
    Raises:
        RuntimeError: If NATS client is not initialized
    """
    if _deps.nats_js is None:
        raise RuntimeError("NATS JetStream not initialized")
    return _deps.nats_js


def get_nats_kv():
    """Get the NATS Key-Value store instance.
    
    Returns:
        KeyValue: The Key-Value store instance
        
    Raises:
        RuntimeError: If NATS Key-Value store is not initialized
    """
    if _deps.nats_kv is None:
        raise RuntimeError("NATS Key-Value store not initialized")
    return _deps.nats_kv

