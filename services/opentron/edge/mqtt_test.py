import asyncio
import json
from datetime import datetime
from aiomqtt import Client


async def main():
    """Test MQTT client that connects and sends messages"""
    
    # MQTT broker addresses
    # Note: MQTT typically uses port 1883, but if your NATS server has MQTT gateway,
    # you may need to adjust ports. Standard MQTT ports: 1883 (non-TLS), 8883 (TLS)
    brokers = [
        ("localhost", 1883),
        ("localhost", 1884),
        ("localhost", 1885),
    ]
    
    # MQTT topic to publish to
    topic = "test/messages"
    
    # Try connecting to each broker (for failover)
    connected = False
    
    for host, port in brokers:
        try:
            print(f"Attempting to connect to MQTT broker at {host}:{port}...")
            async with Client(hostname=host, port=port) as client:
                print(f"✓ Successfully connected to MQTT broker at {host}:{port}!")
                connected = True
                
                # Send a few test messages
                for i in range(5):
                    message = {
                        "message_id": i + 1,
                        "timestamp": datetime.now().isoformat(),
                        "content": f"Test message #{i + 1}",
                        "data": {"value": i * 10}
                    }
                    
                    await client.publish(
                        topic,
                        payload=json.dumps(message),
                        qos=1  # At least once delivery
                    )
                    print(f"✓ Sent message {i + 1} to topic '{topic}': {message['content']}")
                    await asyncio.sleep(0.5)  # Small delay between messages
                
                print(f"\n✓ Successfully sent 5 messages to topic '{topic}'")
                
                print('should show up on nats in "test.messages"')
                
                # Keep connection alive for a bit to ensure messages are sent
                await asyncio.sleep(1)
                
                break  # Successfully connected and sent messages, exit loop
                
        except (ConnectionError, OSError, TimeoutError) as e:
            print(f"✗ Failed to connect to {host}:{port}: {e}")
            continue
        except Exception as e:
            print(f"✗ Error: {e}")
            raise
    
    if not connected:
        print("✗ Could not connect to any MQTT broker")


if __name__ == "__main__":
    asyncio.run(main())
