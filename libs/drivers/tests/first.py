"""Test script for the First machine driver."""

import random
import time
import logging
from puda_drivers.machines import First
from puda_drivers.labware import get_available_labware
from puda_drivers.core import setup_logging

setup_logging(
    enable_file_logging=False,
    log_level=logging.INFO,  # Use logging.DEBUG to see all (DEBUG, INFO, WARNING, ERROR, CRITICAL) logs
)

if __name__ == "__main__":
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
    
    machine.get_absolute_a_position(slot="A3", well="A1")
    # machine.move_electrode(slot="A3", well="A1", height_from_bottom=0)
    
    # machine.record_video(duration_seconds=10, filename="test.mp4")
    machine.start_video_recording()
    machine.attach_tip(slot="A3", well="G8")
    machine.aspirate_from(slot="C2", well="A1", amount=100, height_from_bottom=10)
    # machine.capture_image()
    machine.dispense_to(slot="C2", well="B4", amount=100, height_from_bottom=50)
    machine.drop_tip(slot="C1", well="A1", height_from_bottom=10)
    
    # tiprack_wells = machine.deck["A3"].wells
    # # get pick up pipette one by one and drop it in the trash bin
    # # use random.choice to get a random well from the tiprack
    # for i in range(len(tiprack_wells)):
    #     pickup_well = random.choice(tiprack_wells)
    #     tiprack_wells.remove(pickup_well)
    #     machine.attach_tip("A3", pickup_well)
    #     aspirate_well = random.choice(machine.deck["C2"].wells)
    #     machine.aspirate_from("C2", aspirate_well, 100)
    #     dispense_well = random.choice(machine.deck["C2"].wells)
    #     machine.dispense_to("C2", dispense_well, 100)
    #     machine.drop_tip("C1", "A1")


    machine.stop_video_recording()
    
    # Shutdown machine
    machine.shutdown()
