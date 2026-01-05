"""Test script to poll get_position every second while movement commands are running."""

import asyncio
import logging
import time
from datetime import datetime
from puda_drivers.machines import First
from puda_drivers.core import Position, setup_logging

setup_logging(
    enable_file_logging=False,
    log_level=logging.INFO,
)


async def poll_position(machine: First, stop_event: asyncio.Event):
    """
    Poll get_position every second and print the results.
    
    Args:
        machine: First machine instance
        stop_event: Event to signal when to stop polling
    """
    poll_count = 0
    while not stop_event.is_set():
        try:
            position = await machine.get_position()
            poll_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            qubot_pos = position["qubot"]
            pipette_pos = position["pipette"]
            
            print(f"[{timestamp}] Poll #{poll_count}")
            print(f"  QuBot: X={qubot_pos.get('x', 0):.2f}, "
                  f"Y={qubot_pos.get('y', 0):.2f}, "
                  f"Z={qubot_pos.get('z', 0):.2f}, "
                  f"A={qubot_pos.get('a', 0):.2f}")
            print(f"  Pipette: {pipette_pos} steps")
            print()
            
        except Exception as e:
            print(f"Error polling position: {e}")
        
        # Wait 1 second before next poll
        await asyncio.sleep(1.0)


def run_movements(machine: First):
    """
    Run a sequence of movement commands.
    
    Args:
        machine: First machine instance
    """
    print("Starting movement sequence...")
    
    # Example movement sequence
    positions = [
        Position(x=50, y=-100, z=-50),
        Position(x=150, y=-200, z=-50),
        Position(x=250, y=-300, z=-50),
        Position(x=150, y=-200, z=-50),
        Position(x=50, y=-100, z=-50),
    ]
    
    for i, pos in enumerate(positions, 1):
        print(f"Moving to position {i}/{len(positions)}: {pos}")
        machine.qubot.move_absolute(position=pos)
        time.sleep(0.5)  # Small delay between movements
    
    print("Movement sequence complete!")


async def main():
    """Main function to run position polling and movements concurrently."""
    # Initialize machine
    machine = First(
        qubot_port="/dev/ttyACM0",
        sartorius_port="/dev/ttyUSB0",
        camera_index=0,
    )
    
    try:
        # Startup machine
        print("Starting up machine...")
        machine.startup()
        print("Machine ready!\n")
        
        # Create stop event for polling
        stop_event = asyncio.Event()
        
        # Start position polling task
        polling_task = asyncio.create_task(poll_position(machine, stop_event))
        
        # Run movements in a thread pool (since they're blocking)
        print("Running movements in background...\n")
        await asyncio.to_thread(run_movements, machine)
        
        # Wait a bit more to see final position
        await asyncio.sleep(2)
        
        # Stop polling
        stop_event.set()
        await polling_task
        
        print("\nTest complete!")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        stop_event.set()
        await polling_task
    except Exception as e:
        print(f"\nError: {e}")
        stop_event.set()
        if not polling_task.done():
            await polling_task
    finally:
        # Shutdown machine
        print("\nShutting down machine...")
        machine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

