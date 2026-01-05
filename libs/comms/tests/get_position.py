"""
Simple test script to get telemetry position from the "first" machine
"""
import asyncio
import logging
import nats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

MACHINE_ID = "first"
NAMESPACE = "puda"
POSITION_SUBJECT = f"{NAMESPACE}.{MACHINE_ID}.tlm.pos"


async def handle_position(msg):
    """
    Handle incoming position telemetry messages.
    
    Args:
        msg: NATS message containing position data
    """
    try:
        # Print pure JSON
        print(msg.data.decode())
        
    except Exception as e:
        logger.error("Error handling position message: %s", e)


async def main():
    """Main function - subscribes to position telemetry"""
    servers = ["nats://192.168.50.201:4222", "nats://192.168.50.201:4223", "nats://192.168.50.201:4224"]
    
    try:
        # Connect to NATS
        print("Connecting to NATS servers...")
        nc = await nats.connect(servers=servers)
        print("Connected to NATS")
        print(f"Subscribing to position telemetry: {POSITION_SUBJECT}")
        print("=" * 60)
        print("Waiting for position updates... (Press Ctrl+C to exit)")
        print("=" * 60)
        print()
        
        # Subscribe to position telemetry
        sub = await nc.subscribe(POSITION_SUBJECT, cb=handle_position)
        
        # Keep running until interrupted
        try:
            await asyncio.Event().wait()  # Wait indefinitely
        except KeyboardInterrupt:
            print("\n\nStopping position monitor...")
            await sub.unsubscribe()
            await nc.close()
            print("Disconnected from NATS")
        
    except Exception as e:
        logger.error("Error: %s", e)
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

