"""Test script to poll get_position every second during machine operations."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from puda_drivers.machines import First
from puda_drivers.labware import get_available_labware
from puda_drivers.core import setup_logging

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
    while not stop_event.is_set():
        try:
            position = await machine.get_position()
            timestamp = datetime.now(timezone.utc).isoformat()
            result = {
                "timestamp": timestamp,
                "qubot": position.get("qubot", {}),
                "pipette": position.get("pipette", ""),
            }
            print(json.dumps(result))
        except (ValueError, IOError, RuntimeError) as e:
            timestamp = datetime.now(timezone.utc).isoformat()
            result = {
                "timestamp": timestamp,
                "qubot": {},
                "pipette": "",
                "error": str(e),
            }
            print(json.dumps(result))
        
        # Wait 1 second, but check stop_event periodically
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            break
        except asyncio.TimeoutError:
            continue


def run_operations(machine: First):
    """
    Run the machine operations synchronously.
    
    Args:
        machine: First machine instance
    """
    machine.start_video_recording()
    machine.attach_tip(slot="A3", well="G8")
    machine.aspirate_from(slot="C2", well="A1", amount=100, height_from_bottom=10)
    machine.dispense_to(slot="C2", well="B4", amount=100, height_from_bottom=50)
    machine.drop_tip(slot="C1", well="A1", height_from_bottom=10)
    machine.stop_video_recording()


async def main():
    """Main async function to run operations and position polling concurrently."""
    # Connect machine
    machine = First(
        qubot_port="/dev/ttyACM0",
        sartorius_port="/dev/ttyUSB0",
        camera_index=0,
    )
    
    # View available labware
    print(get_available_labware())

    # Define deck layout declaratively and load all at once
    machine.load_deck(
        {
            "C1": "trash_bin",
            "C2": "polyelectric_8_wellplate_30000ul",
            "A3": "opentrons_96_tiprack_300ul",
        }
    )

    print(machine.deck)
    print(machine.deck["C2"])

    machine.startup()  # Connects all controllers, homes gantry, and initializes pipette
    
    # Create event to signal when operations are done
    stop_event = asyncio.Event()
    
    # Start position polling task
    polling_task = asyncio.create_task(poll_position(machine, stop_event))
    
    # Run operations in a thread pool (since they're blocking)
    try:
        await asyncio.to_thread(run_operations, machine)
    finally:
        # Signal polling to stop
        stop_event.set()
        # Wait for polling task to finish
        await polling_task
    
    # Shutdown machine
    machine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

