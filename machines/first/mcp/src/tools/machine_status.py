"""
Machine Status Tool

Tool for retrieving machine status from NATS Key-Value store.
"""

import json
from nats.js.errors import NotFoundError
from ..utils.config import Config
from ..dependencies import get_nats_kv


async def get_machine_status() -> dict:
    """Get the current status of the machine from NATS Key-Value store.
    
    Retrieves the machine status stored in the NATS JetStream Key-Value bucket.
    The status includes the current state and operational information for the machine.
    
    Returns:
        dict: Machine status information including state and operational data.
        
    Raises:
        Exception: If the machine status cannot be found in the KV store.
    """
    try:
        # Use the NATS Key-Value store from dependencies
        kv = get_nats_kv()
        entry = await kv.get(Config.MACHINE_ID)
        
        if entry:
            status = json.loads(entry.value.decode())
            return status
        else:
            return {"error": f"Could not find status for {Config.MACHINE_ID}"}
        
    except NotFoundError as e:
        return {"error": f"KV bucket or key not found for {Config.MACHINE_ID}: {e}"}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse status JSON for {Config.MACHINE_ID}: {e}"}
    except (KeyError, AttributeError) as e:
        return {"error": f"Invalid status data format for {Config.MACHINE_ID}: {e}"}
    except RuntimeError as e:
        # Connection not established
        return {"error": f"NATS connection error: {e}"}
    except Exception as e:  # pylint: disable=broad-except
        # Catch-all for any unexpected errors (NATS connection, network, etc.)
        return {"error": f"Unexpected error retrieving status for {Config.MACHINE_ID}: {e}"}

