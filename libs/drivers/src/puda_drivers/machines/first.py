"""
First machine class containing Deck, RepRapController, and SartoriusController.

This class demonstrates the integration of:
- RepRapController: Handles motion control (hardware-specific)
- Deck: Manages labware layout (configuration-agnostic)
- SartoriusController: Handles liquid handling operations
"""

import logging
import time
from pathlib import Path
from typing import Optional, Dict, Tuple, Type, Union
import numpy as np
from puda_drivers.move import RepRapController, Deck
from puda_drivers.core import Position
from puda_drivers.transfer.liquid.sartorius import SartoriusController
from puda_drivers.labware import StandardLabware
from puda_drivers.cv import CameraController

logger = logging.getLogger(__name__)


class First:
    """
    First machine class integrating motion control, deck management, liquid handling, and camera.
    
    The deck has 16 slots arranged in a 4x4 grid (A1-D4).
    Each slot's origin location is stored for absolute movement calculation.
    """
    CEILING_HEIGHT = 192.2 # Height from z and a origin to the deck

    # Pipette
    Z_ORIGIN = Position(x=0, y=0, z=0)
    TIP_LENGTH = 59 # Pipette tip length in mm
    
    # Electrode
    A_ORIGIN = Position(x=60, y=0, a=0)
    ELECTRODE_LENGTH = 2 # Electrode length in mm
    
    # Default axis limits - customize based on your hardware
    DEFAULT_AXIS_LIMITS = {
        "X": (0, 330),
        "Y": (-440, 0),
        "Z": (-140, 0),
        "A": (-175, 0),
    }
    
    # Slot origins (the bottom left corner of each deck slot relative to the deck origin)
    SLOT_ORIGINS = {
        "A1": Position(x=-2, y=-424),
        "A2": Position(x=98, y=-424),
        "A3": Position(x=198, y=-424),
        "A4": Position(x=298, y=-424),
        "B1": Position(x=-2, y=-274),
        "B2": Position(x=98, y=-274),
        "B3": Position(x=198, y=-274),
        "B4": Position(x=298, y=-274),
        "C1": Position(x=-2, y=-124),
        "C2": Position(x=98, y=-124),
        "C3": Position(x=198, y=-124),
        "C4": Position(x=298, y=-124),
    }
    
    def __init__(
        self,
        qubot_port: Optional[str] = None,
        sartorius_port: Optional[str] = None,
        camera_index: Optional[Union[int, str]] = None,
        axis_limits: Optional[Dict[str, Tuple[float, float]]] = None,
    ):
        """
        Initialize the First machine.

        qubot_port, sartorius_port, and camera_index must all be specified; otherwise ValueError is raised.

        Args:
            qubot_port: Serial port for RepRapController (e.g., '/dev/ttyACM0').
            sartorius_port: Serial port for SartoriusController (e.g., '/dev/ttyUSB0').
            camera_index: Camera device index or device path/identifier.
            axis_limits: Dictionary mapping axis names to (min, max) limits. Defaults to DEFAULT_AXIS_LIMITS.

        Raises:
            ValueError: If qubot_port, sartorius_port, or camera_index is not specified.
        """
        if qubot_port is None:
            raise ValueError("qubot_port is required")
        if sartorius_port is None:
            raise ValueError("sartorius_port is required")
        if camera_index is None:
            raise ValueError("camera_index is required")

        # Initialize deck
        self.deck = Deck(rows=4, cols=4)

        self.qubot = RepRapController(port_name=qubot_port)
        limits = axis_limits or self.DEFAULT_AXIS_LIMITS
        for axis, (min_val, max_val) in limits.items():
            self.qubot.set_axis_limits(axis, min_val, max_val)

        self.pipette = SartoriusController(port_name=sartorius_port)
        self.camera = CameraController(camera_index=camera_index)

        logger.info(
            "First machine initialized: qubot_port=%s, sartorius_port=%s, camera_index=%s",
            qubot_port,
            sartorius_port,
            camera_index,
        )
        
    def startup(self):
        """
        Start up the machine by connecting all controllers and initializing subsystems.
        
        This method:
        - Connects to all controllers (gantry, pipette, camera)
        - Homes the gantry to establish a known position
        - Initializes the pipette to reset it to a known state
        
        The machine is ready for operations after this method completes.
        """
        logger.info("Starting up machine and connecting all controllers")
        self.qubot.connect()
        self.pipette.connect()
        self.camera.connect()
        logger.info("All controllers connected successfully")

        logger.info("Homing gantry...")
        self.qubot.home()
        logger.info("Initializing pipette...")
        self.pipette.initialize()
        time.sleep(3)  # need to wait for the pipette to initialize
        logger.info("Machine startup complete - ready for operations")
    
    def home(self):
        """
        Home the qubot gantry to establish a known position.
        
        This method homes the gantry to its reference position, which is useful
        for establishing a known starting point before operations or after
        potential position drift.
        """
        logger.info("Homing qubot gantry...")
        self.qubot.home()
        self.pipette.initialize()
        logger.info("Qubot gantry homing complete")
        
    def shutdown(self):
        """
        Gracefully shut down the machine by disconnecting all controllers.
        
        This method ensures all connections are properly closed and resources are released.
        """
        logger.info("Shutting down machine and disconnecting all controllers")
        self.qubot.disconnect()
        self.pipette.disconnect()
        self.camera.disconnect()
        logger.info("Machine shutdown complete")
    
    def wait(self, seconds: float):
        """
        Wait for a specified number of seconds.
        
        Args:
            seconds: Number of seconds to wait (can be a float for fractional seconds)
        """
        logger.debug("Waiting for %.2f seconds", seconds)
        time.sleep(seconds)
        logger.debug("Waited for %.2f seconds", seconds)
        
    ### Queue (public commands) ###
    async def get_position(self) -> Dict[str, Union[Dict[str, float], int]]:
        """
        Get the current position of the machine. Queries only configured controllers.

        Returns:
            Dictionary containing the current position of the machine and its components (qubot, pipette).
        """
        qubot_position = await self.qubot.get_position()
        sartorius_position = await self.pipette.get_position()
        return {
            "qubot": qubot_position.to_dict(),
            "pipette": sartorius_position,
        }
    
    def get_deck(self):
        """
        Get the current deck layout.
        
        Returns:
            Dictionary mapping deck slot names (e.g., "A1") to labware classes.
        
        Raises:
            None
        """
        return self.deck.to_dict()
        
    def load_labware(self, deck_slot: str, labware_name: str):
        """
        Load a labware object into a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            labware_name: Name of the labware class to load
        
        Raises:
            KeyError: If deck_slot is not found in deck
        """
        logger.info("Loading labware '%s' into deck slot '%s'", labware_name, deck_slot)
        self.deck.load_labware(slot=deck_slot, labware_name=labware_name)
        logger.debug("Labware '%s' loaded into deck slot '%s'", labware_name, deck_slot)

    def remove_labware(self, deck_slot: str):
        """
        Remove labware from a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
        
        Raises:
            KeyError: If deck_slot is not found in deck
        """
        self.deck.empty_slot(slot=deck_slot)
        logger.debug("Deck slot '%s' emptied", deck_slot)
        
    def load_deck(self, layout: Dict[str, Type[StandardLabware]]):
        """
        Load multiple labware into the deck at once.
        
        Args:
            layout: Dictionary mapping deck slot names (e.g., "A1", "B1", "C1") to
                    labware names/files (e.g., opentrons_96_tiprack, trash_bin).
            
        Example:
            machine.load_deck(
                layout={
                    "A1": "opentrons_96_tiprack",
                    "B1": "trash_bin",
                    "C1": "polyelectric_8_wellplate_30000ul",
                }
            )
        """
        logger.info("Loading deck layout with %d labware items", len(layout))
        for deck_slot, labware_name in layout.items():
            self.load_labware(deck_slot=deck_slot, labware_name=labware_name)
        logger.info("Deck layout loaded successfully")
        
    ### Pipette operations ###
    def attach_tip(self, deck_slot: str, well_name: str):
        """
        Attach a tip from a deck slot and well.

        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Well name (e.g., 'A1' for a well in a tiprack)
        
        Note:
            This method is idempotent - if a tip is already attached, it will
            log a warning and return successfully without raising an error.
        """
        if self.pipette.is_tip_attached():
            logger.warning("Tip already attached - skipping attachment (idempotent operation)")
            return
        
        logger.info("Attaching tip from deck slot '%s'%s", deck_slot, f", well '{well_name}'" if well_name else "")
        pos = self._get_absolute_z_position(deck_slot, well_name)
        logger.debug("Moving to position %s for tip attachment", pos)
        # return the offset from the origin
        self.qubot.move_absolute(position=pos)
        
        # attach tip (move slowly down)
        labware = self.deck[deck_slot]
        if labware is None:
            logger.error("Cannot attach tip: no labware loaded in deck slot '%s'", deck_slot)
            raise ValueError(f"No labware loaded in deck slot '{deck_slot}'. Load labware before attaching tips.")
        logger.debug("Moving down by %s mm to insert tip", labware.get_insert_depth())
        self.qubot.move_relative(
            position=Position(z=-labware.get_insert_depth()),
            feed=500
        )
        self.pipette.set_tip_attached(attached=True)
        logger.info("Tip attached successfully, homing Z axis")
        # must home Z axis after, as pressing in tip might cause it to lose steps
        self.qubot.home(axis="Z")
        logger.debug("Z axis homed after tip attachment")
        
    def drop_tip(self, *, deck_slot: str, well_name: str, height_from_bottom: float = 0.0):
        """
        Drop a tip into a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Well name within the deck slot (e.g., 'A1' for a well in a tiprack)
            height_from_bottom: Height from the bottom of the well in mm. Defaults to 0.0.
                               Must be non-negative. Positive values move up from the bottom.
        
        Raises:
            ValueError: If no tip is attached, if height_from_bottom is negative, or if
                       the resulting position is outside the Z axis limits.
        """
        if height_from_bottom < 0:
            logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        if not self.pipette.is_tip_attached():
            logger.error("Cannot drop tip: no tip attached")
            raise ValueError("Tip not attached")
        
        logger.info("Dropping tip into deck slot '%s', well '%s'", deck_slot, well_name)
        pos = self._get_absolute_z_position(deck_slot, well_name)
        # add height from bottom
        pos += Position(z=height_from_bottom)
        logger.debug("Moving to position %s for tip drop", pos)
        self.qubot.move_absolute(position=pos)

        logger.debug("Ejecting tip")
        self.pipette.eject_tip()
        time.sleep(5)
        self.pipette.set_tip_attached(attached=False)
        logger.info("Tip dropped successfully")
        
    def aspirate_from(self, *, deck_slot: str, well_name: str, amount: int, height_from_bottom: float = 0.0):
        """
        Aspirate a volume of liquid from a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Well name within the deck slot (e.g., 'A1')
            amount: Volume to aspirate in µL
            height_from_bottom: Height from the bottom of the well in mm. Defaults to 0.0.
                               Must be non-negative. Positive values move up from the bottom.
        
        Raises:
            ValueError: If no tip is attached, if height_from_bottom is negative, or if
                       the resulting position is outside the Z axis limits.
        """
        if height_from_bottom < 0:
            logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        if not self.pipette.is_tip_attached():
            logger.error("Cannot aspirate: no tip attached")
            raise ValueError("Tip not attached")
        
        logger.info("Aspirating %d µL from deck slot '%s', well '%s'", amount, deck_slot, well_name)

        pos = self._get_absolute_z_position(deck_slot, well_name)
        # add height from bottom
        pos += Position(z=height_from_bottom)
        # subtract insert depth to get the bottom of the well
        pos -= Position(z=self.deck[deck_slot].get_insert_depth())

        logger.debug("Moving Z axis to position %s", pos)
        self.qubot.move_absolute(position=pos)
        logger.debug("Aspirating %d µL", amount)
        self.pipette.aspirate(amount=amount)
        time.sleep(5)
        logger.info("Aspiration completed: %d µL from deck slot '%s', well '%s'", amount, deck_slot, well_name)
        
    def dispense_to(self, *, deck_slot: str, well_name: str, amount: int, height_from_bottom: float = 0.0):
        """
        Dispense a volume of liquid to a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Well name within the deck slot (e.g., 'A1')
            amount: Volume to dispense in µL
            height_from_bottom: Height from the bottom of the well in mm. Defaults to 0.0.
                               Must be non-negative. Positive values move up from the bottom.
        
        Raises:
            ValueError: If no tip is attached, if height_from_bottom is negative, or if
                       the resulting position is outside the Z axis limits.
        """
        if height_from_bottom < 0:
            logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        if not self.pipette.is_tip_attached():
            logger.error("Cannot dispense: no tip attached")
            raise ValueError("Tip not attached")
        
        logger.info("Dispensing %d µL to deck slot '%s', well '%s'", amount, deck_slot, well_name)

        pos = self._get_absolute_z_position(deck_slot, well_name)
        # add height from bottom
        pos += Position(z=height_from_bottom)
        # subtract insert depth to get the bottom of the well
        pos -= Position(z=self.deck[deck_slot].get_insert_depth())

        logger.debug("Moving Z axis to position %s", pos)
        self.qubot.move_absolute(position=pos)
        logger.debug("Dispensing %d µL", amount)
        self.pipette.dispense(amount=amount)
        time.sleep(5)
        logger.info("Dispense completed: %d µL to deck slot '%s', well '%s'", amount, deck_slot, well_name)
        
    def blowout(self, *, return_position: Optional[int] = None):
        """
        Blow out the pipette.
        
        Args:
            return_position: Optional position to return to after blowout. Defaults to None.
        """
        logger.info("Blowing out pipette")
        self.pipette.run_blowout(return_position=return_position)
        logger.info("Blowout completed")

    # Electrode operations
    def move_electrode(self, deck_slot: str, well_name: str, height_from_bottom: float = 0.0):
        """
        Move the electrode to a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Well name within the deck slot (e.g., 'A1')
            height_from_bottom: Height from the bottom of the well in mm. Defaults to 0.0.
                               Must be non-negative. Positive values move up from the bottom.
        
        Raises:
            ValueError: If height_from_bottom is negative.
        """
        if height_from_bottom < 0:
            logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        pos = self._get_absolute_a_position(deck_slot, well_name)
        pos += Position(a=height_from_bottom)
        self.qubot.move_absolute(position=pos)
        logger.info("Electrode moved to deck slot '%s', well '%s' at height %s mm from bottom", deck_slot, well_name, height_from_bottom)
        
    # Helper methods
    def _get_slot_origin(self, deck_slot: str) -> Position:
        """
        Get the origin coordinates of a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            
        Returns:
            Position for the deck slot origin
            
        Raises:
            KeyError: If deck_slot name is invalid
        """
        deck_slot = deck_slot.upper()
        if deck_slot not in self.SLOT_ORIGINS:
            logger.error("Invalid deck slot name: '%s'. Must be one of %s", deck_slot, list(self.SLOT_ORIGINS.keys()))
            raise KeyError(f"Invalid deck slot name: {deck_slot}. Must be one of {list(self.SLOT_ORIGINS.keys())}")
        pos = self.SLOT_ORIGINS[deck_slot]
        logger.debug("Deck slot origin for '%s': %s", deck_slot, pos)
        return pos
    
    def _get_absolute_z_position(self, deck_slot: str, well_name: Optional[str] = None) -> Position:
        """
        Get the absolute position for a deck slot (and optionally a well within that deck slot) based on the origin
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Optional well name within the deck slot (e.g., 'A1' for a well in a tiprack)
            
        Returns:
            Position with absolute coordinates
            
        Raises:
            ValueError: If well_name is specified but no labware is loaded in the deck slot
        """
        # Get deck slot origin
        pos = self._get_slot_origin(deck_slot)

        # relative well position from deck slot origin
        if well_name:
            labware = self.deck[deck_slot]
            if labware is None:
                logger.error("Cannot get well position: no labware loaded in deck slot '%s'", deck_slot)
                raise ValueError(f"No labware loaded in deck slot '{deck_slot}'. Load labware before accessing wells.")
            well_pos = labware.get_well_position(well_name).get_xy()
            # the deck is rotated 90 degrees clockwise for this machine
            pos += well_pos.swap_xy()
            # get z
            pos += Position(z=labware.get_height() - self.CEILING_HEIGHT)
            # if tip attached, add tip length
            if self.pipette.is_tip_attached():
                pos += Position(z=self.TIP_LENGTH)
            logger.debug("Absolute Z position for deck slot '%s', well '%s': %s", deck_slot, well_name, pos)
        else:
            logger.debug("Absolute Z position for deck slot '%s': %s", deck_slot, pos)
        return pos
    
    def _get_absolute_a_position(self, deck_slot: str, well_name: Optional[str] = None) -> Position:
        """
        Get the absolute position for a deck slot (and optionally a well within that deck slot) based on the origin
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
            well_name: Optional well name within the deck slot (e.g., 'A1' for a well in a tiprack)
            
        Returns:
            Position with absolute coordinates
            
        Raises:
            ValueError: If well_name is specified but no labware is loaded in the deck slot
        """
        # get x and y
        pos = self._get_slot_origin(deck_slot)
        pos -= self.A_ORIGIN # subtract the origin to get the absolute position
        
        # Get labware for a-axis positioning
        labware = self.deck[deck_slot]
        if labware is None:
            logger.error("Cannot get electrode position: no labware loaded in deck slot '%s'", deck_slot)
            raise ValueError(f"No labware loaded in deck slot '{deck_slot}'. Load labware before moving electrode.")
        
        # get x and y for well if specified
        if well_name:
            well_pos = labware.get_well_position(well_name).get_xy()
            pos += well_pos.swap_xy()
        
        # get a (applies to both with and without well_name)
        pos += Position(a=labware.get_height() - self.CEILING_HEIGHT)
        pos += Position(a=self.ELECTRODE_LENGTH)
        
        if well_name:
            logger.debug("Absolute A position for deck slot '%s', well '%s': %s", deck_slot, well_name, pos)
        else:
            logger.debug("Absolute A position for deck slot '%s': %s", deck_slot, pos)
        
        return pos

   ### Camera operations ###
    
    def start_video_recording(
        self,
        filename: Optional[Union[str, Path]] = None,
        fps: Optional[float] = None
    ) -> Path:
        """
        Start recording a video.
        
        Args:
            filename: Optional filename for the video. If not provided, a timestamped
                    filename will be generated. If provided without extension, .mp4 will be added.
            fps: Optional frames per second for the video. Defaults to 30.0 if not specified.
        
        Returns:
            Path to the video file where recording is being saved
            
        Raises:
            IOError: If camera is not connected or recording fails to start
            ValueError: If already recording
        """
        return self.camera.start_video_recording(filename=filename, fps=fps)
    
    def stop_video_recording(self) -> Optional[Path]:
        """
        Stop recording a video.
        
        Returns:
            Path to the saved video file, or None if no recording was in progress
            
        Raises:
            IOError: If video writer fails to release
        """
        return self.camera.stop_video_recording()
    
    def record_video(
        self,
        duration_seconds: float,
        filename: Optional[Union[str, Path]] = None,
        fps: Optional[float] = None
    ) -> Path:
        """
        Record a video for a specified duration.
        
        Args:
            duration_seconds: Duration of the video in seconds
            filename: Optional filename for the video. If not provided, a timestamped
                    filename will be generated. If provided without extension, .mp4 will be added.
            fps: Optional frames per second for the video. Defaults to 30.0 if not specified.
        
        Returns:
            Path to the saved video file
            
        Raises:
            IOError: If camera is not connected or recording fails
        """
        return self.camera.record_video(
            duration_seconds=duration_seconds,
            filename=filename,
            fps=fps
        )
    
    def capture_image(
        self,
        save: bool = False,
        filename: Optional[Union[str, Path]] = None
    ) -> np.ndarray:
        """
        Capture a single image from the camera.
        
        Args:
            save: If True, save the image to the captures folder
            filename: Optional filename for the saved image. If not provided and save=True,
                     a timestamped filename will be generated. If provided without extension,
                     .jpg will be added.
        
        Returns:
            Captured image as a numpy array (BGR format)
            
        Raises:
            IOError: If camera is not connected or capture fails
        """
        return self.camera.capture_image(save=save, filename=filename)
    
    ### Control (immediate commands) ###
    def pause(self):
        """
        Pause the execution of queued commands.
        """
        logger.info("Pausing machine")
    
    def resume(self):
        """
        Resume the execution of queued commands.
        """
        logger.info("Resuming machine")

    def cancel(self):
        """
        Cancel the execution of queued commands.
        """
        logger.info("Cancelling machine")