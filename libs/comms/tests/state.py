"""
Test script to read and monitor machine status from NATS KV store
"""
import asyncio
import json
import logging
from datetime import datetime
import nats
from nats.js.client import JetStreamContext

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "first"
KV_BUCKET_NAME = f"MACHINE_STATE_{MACHINE_ID.replace('.', '-')}"


async def read_status(js: JetStreamContext, machine_id: str) -> dict:
    """
    Read machine status from KV store.
    
    Args:
        js: JetStream context
        machine_id: Machine identifier
    
    Returns:
        Dictionary with status data or None if not found
    """
    try:
        kv = await js.key_value(KV_BUCKET_NAME)
        entry = await kv.get(machine_id)
        
        if entry:
            status = json.loads(entry.value.decode())
            return status
        else:
            return None
    except Exception as e:
        logger.error("Error reading status from KV store: %s", e)
        return None


async def watch_status(js: JetStreamContext, machine_id: str, interval: float = 1.0):
    """
    Continuously watch and display machine status.
    
    Args:
        js: JetStream context
        machine_id: Machine identifier
        interval: Polling interval in seconds
    """
    print(f"Monitoring status for machine: {machine_id}")
    print(f"KV Bucket: {KV_BUCKET_NAME}")
    print(f"Polling interval: {interval} second(s)")
    print("=" * 60)
    print("Press Ctrl+C to exit")
    print("=" * 60)
    
    while True:
        try:
            state = await read_status(js, machine_id)
            timestamp = datetime.now().strftime('%H:%M:%S')
            
            if state is None:
                print(f"[{timestamp}] Status: Not found in KV store")
            else:
                # Display all KV entries
                kv_items = ', '.join([f"{k}: {v}" for k, v in state.items()])
                print(f"[{timestamp}] {kv_items}")
            
            await asyncio.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n\nStopping status monitor...")
            break
        except Exception as e:
            logger.error("Error watching status: %s", e)
            await asyncio.sleep(interval)


async def main():
    """Main function - continuously monitors status"""
    servers = ["nats://192.168.50.201:4222", "nats://192.168.50.201:4223", "nats://192.168.50.201:4224"]
    
    try:
        # Connect to NATS
        print("Connecting to NATS servers...")
        nc = await nats.connect(servers=servers, connect_timeout=10)
        js = nc.jetstream()
        print("Connected to NATS\n")
        
        # Continuously monitor status (every 1 second)
        await watch_status(js, MACHINE_ID, interval=1.0)
        
        await nc.close()
        
    except Exception as e:
        logger.error("Error: %s", e)
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

