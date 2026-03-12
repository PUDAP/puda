"""
PipQuBotV3 machine class containing Deck, GrblHALController, and SartoriusController.

This class integrates:
- GrblHALController: Handles motion control (hardware-specific)
- Deck: Manages labware layout (configuration-agnostic)
- SartoriusController: Handles liquid handling operations
"""

import logging
import time
from typing import Optional, Dict, Tuple, Type, Union
from puda_drivers.move import GrblHALController, Deck
from puda_drivers.core import Position
from puda_drivers.transfer.liquid.sartorius import SartoriusController
from puda_drivers.labware import StandardLabware


class PipQuBotV3:
    """
    PipQuBotV3 machine class integrating motion control, deck management, and liquid handling.
    
    The deck has 8 slots arranged in a 2x4 grid (A1-D2).
    Each slot's origin location is stored for absolute movement calculation.
    """
    
    # origin position of Z axis
    Z_ORIGIN = Position(x=0, y=0, z=0)
    
    # Default axis limits - customize based on your hardware
    DEFAULT_AXIS_LIMITS = {
        "X": (0, 160),
        "Y": (-430, 0),
        "Z": (-140, 0),
    }
    
    # Height from z origin to the deck
    CEILING_HEIGHT = 170
    
    # Pipette Tip length
    TIP_LENGTH = 96 # mm
    
    # Slot origins (the bottom left corner of the slot relative to the deck origin)
    SLOT_ORIGINS = {
        "A1": Position(x=1.5, y=-461.5),
        "A2": Position(x=101.5, y=-461.5),
        "B1": Position(x=1.5, y=-311.5),
        "B2": Position(x=101.5, y=-311.5),
        "C1": Position(x=1.5, y=-161.5),
        "C2": Position(x=101.5, y=-161.5),
        "D1": Position(x=1.5, y=-11.5),
        "D2": Position(x=101.5, y=-11.5),
    }
    
    def __init__(
        self,
        qubot_port: Optional[str] = None,
        sartorius_port: Optional[str] = None,
        axis_limits: Optional[Dict[str, Tuple[float, float]]] = None,
    ):
        """
        Initialize the First machine.

        qubot_port and sartorius_port must both be specified; otherwise ValueError is raised.

        Args:
            qubot_port: Serial port for GrblHALController (e.g., '/dev/ttyACM0').
            sartorius_port: Serial port for SartoriusController (e.g., '/dev/ttyUSB0').
            axis_limits: Dictionary mapping axis names to (min, max) limits. Defaults to DEFAULT_AXIS_LIMITS.

        Raises:
            ValueError: If qubot_port or sartorius_port is not specified.
        """
        if qubot_port is None:
            raise ValueError("qubot_port is required")
        if sartorius_port is None:
            raise ValueError("sartorius_port is required")

        # Initialize deck
        self.deck = Deck(rows=4, cols=4)

        self.qubot = GrblHALController(port_name=qubot_port)
        limits = axis_limits or self.DEFAULT_AXIS_LIMITS
        for axis, (min_val, max_val) in limits.items():
            self.qubot.set_axis_limits(axis, min_val, max_val)

        self.pipette = SartoriusController(port_name=sartorius_port)

        self._logger = logging.getLogger(__name__)
        self._logger.info(
            "First machine initialized: qubot_port=%s, sartorius_port=%s",
            qubot_port,
            sartorius_port,
        )
        
    def startup(self):
        """
        Start up the machine by connecting all controllers and initializing subsystems.
        
        This method:
        - Connects to all controllers (gantry, pipette)
        - Homes the gantry to establish a known position
        - Initializes the pipette to reset it to a known state
        
        The machine is ready for operations after this method completes.
        """
        self._logger.info("Starting up machine and connecting all controllers")
        self.qubot.connect()
        self.pipette.connect()
        self._logger.info("All controllers connected successfully")

        self._logger.info("Homing gantry...")
        self.qubot.home()
        self._logger.info("Initializing pipette...")
        self.pipette.initialize()
        time.sleep(3)  # need to wait for the pipette to initialize
        self._logger.info("Machine startup complete - ready for operations")
    
    def home(self):
        """
        Home the qubot gantry to establish a known position.
        
        This method homes the gantry to its reference position, which is useful
        for establishing a known starting point before operations or after
        potential position drift.
        """
        self._logger.info("Homing qubot gantry...")
        self.qubot.home()
        self.pipette.initialize()
        self._logger.info("Qubot gantry homing complete")
        
    def shutdown(self):
        """
        Gracefully shut down the machine by disconnecting all controllers.
        
        This method ensures all connections are properly closed and resources are released.
        """
        self._logger.info("Shutting down machine and disconnecting all controllers")
        self.qubot.disconnect()
        self.pipette.disconnect()
        self._logger.info("Machine shutdown complete")
    
    def wait(self, seconds: float):
        """
        Wait for a specified number of seconds.
        
        Args:
            seconds: Number of seconds to wait (can be a float for fractional seconds)
        """
        self._logger.debug("Waiting for %.2f seconds", seconds)
        time.sleep(seconds)
        self._logger.debug("Waited for %.2f seconds", seconds)
        
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
        self._logger.info("Loading labware '%s' into deck slot '%s'", labware_name, deck_slot)
        self.deck.load_labware(slot=deck_slot, labware_name=labware_name)
        self._logger.debug("Labware '%s' loaded into deck slot '%s'", labware_name, deck_slot)

    def remove_labware(self, deck_slot: str):
        """
        Remove labware from a deck slot.
        
        Args:
            deck_slot: Deck slot name (e.g., 'A1', 'B2')
        
        Raises:
            KeyError: If deck_slot is not found in deck
        """
        self.deck.empty_slot(slot=deck_slot)
        self._logger.debug("Deck slot '%s' emptied", deck_slot)
        
    def load_deck(self, deck_layout: Dict[str, Type[StandardLabware]]):
        """
        Load multiple labware into the deck at once.
        
        Args:
            deck_layout: Dictionary mapping deck slot names (e.g., "A1") to labware classes.
                        Each class will be instantiated automatically.
        
        Example:
            machine.load_deck({
                "A1": Opentrons96TipRack300,
                "B1": Opentrons96TipRack300,
                "C1": Rubbish,
            })
        """
        self._logger.info("Loading deck layout with %d labware items", len(deck_layout))
        for deck_slot, labware_name in deck_layout.items():
            self.load_labware(deck_slot=deck_slot, labware_name=labware_name)
        self._logger.info("Deck layout loaded successfully")
        
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
            self._logger.warning("Tip already attached - skipping attachment (idempotent operation)")
            return
        
        self._logger.info("Attaching tip from deck slot '%s'%s", deck_slot, f", well '{well_name}'" if well_name else "")
        pos = self._get_absolute_z_position(deck_slot, well_name)
        self._logger.debug("Moving to position %s for tip attachment", pos)
        # return the offset from the origin
        self.qubot.move_absolute(position=pos)
        
        # attach tip (move slowly down)
        labware = self.deck[deck_slot]
        if labware is None:
            self._logger.error("Cannot attach tip: no labware loaded in deck slot '%s'", deck_slot)
            raise ValueError(f"No labware loaded in deck slot '{deck_slot}'. Load labware before attaching tips.")
        self._logger.debug("Moving down by %s mm to insert tip", labware.get_insert_depth())
        self.qubot.move_relative(
            position=Position(z=-labware.get_insert_depth()),
            feed=500
        )
        self.pipette.set_tip_attached(attached=True)
        self._logger.info("Tip attached successfully, homing Z axis")
        # must home Z axis after, as pressing in tip might cause it to lose steps
        self.qubot.home(axis="Z")
        self._logger.debug("Z axis homed after tip attachment")
        
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
            self._logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        if not self.pipette.is_tip_attached():
            self._logger.error("Cannot drop tip: no tip attached")
            raise ValueError("Tip not attached")
        
        self._logger.info("Dropping tip into deck slot '%s', well '%s'", deck_slot, well_name)
        pos = self._get_absolute_z_position(deck_slot, well_name)
        # add height from bottom
        pos += Position(z=height_from_bottom)
        self._logger.debug("Moving to position %s for tip drop", pos)
        self.qubot.move_absolute(position=pos)

        self._logger.debug("Ejecting tip")
        self.pipette.eject_tip()
        time.sleep(5)
        self.pipette.set_tip_attached(attached=False)
        self._logger.info("Tip dropped successfully")
        
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
            self._logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        if not self.pipette.is_tip_attached():
            self._logger.error("Cannot aspirate: no tip attached")
            raise ValueError("Tip not attached")
        
        self._logger.info("Aspirating %d µL from deck slot '%s', well '%s'", amount, deck_slot, well_name)

        pos = self._get_absolute_z_position(deck_slot, well_name)
        # add height from bottom
        pos += Position(z=height_from_bottom)
        # subtract insert depth to get the bottom of the well
        pos -= Position(z=self.deck[deck_slot].get_insert_depth())

        self._logger.debug("Moving Z axis to position %s", pos)
        self.qubot.move_absolute(position=pos)
        self._logger.debug("Aspirating %d µL", amount)
        self.pipette.aspirate(amount=amount)
        time.sleep(5)
        self._logger.info("Aspiration completed: %d µL from deck slot '%s', well '%s'", amount, deck_slot, well_name)
        
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
            self._logger.error("height_from_bottom must be non-negative, got %f", height_from_bottom)
            raise ValueError(f"height_from_bottom must be non-negative, got {height_from_bottom}")
        
        if not self.pipette.is_tip_attached():
            self._logger.error("Cannot dispense: no tip attached")
            raise ValueError("Tip not attached")
        
        self._logger.info("Dispensing %d µL to deck slot '%s', well '%s'", amount, deck_slot, well_name)

        pos = self._get_absolute_z_position(deck_slot, well_name)
        # add height from bottom
        pos += Position(z=height_from_bottom)
        # subtract insert depth to get the bottom of the well
        pos -= Position(z=self.deck[deck_slot].get_insert_depth())

        self._logger.debug("Moving Z axis to position %s", pos)
        self.qubot.move_absolute(position=pos)
        self._logger.debug("Dispensing %d µL", amount)
        self.pipette.dispense(amount=amount)
        time.sleep(5)
        self._logger.info("Dispense completed: %d µL to deck slot '%s', well '%s'", amount, deck_slot, well_name)
        
    def blowout(self, *, return_position: Optional[int] = None):
        """
        Blow out the pipette.
        
        Args:
            return_position: Optional position to return to after blowout. Defaults to None.
        """
        self._logger.info("Blowing out pipette")
        self.pipette.run_blowout(return_position=return_position)
        self._logger.info("Blowout completed")

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
            self._logger.error("Invalid deck slot name: '%s'. Must be one of %s", deck_slot, list(self.SLOT_ORIGINS.keys()))
            raise KeyError(f"Invalid deck slot name: {deck_slot}. Must be one of {list(self.SLOT_ORIGINS.keys())}")
        pos = self.SLOT_ORIGINS[deck_slot]
        self._logger.debug("Deck slot origin for '%s': %s", deck_slot, pos)
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
                self._logger.error("Cannot get well position: no labware loaded in deck slot '%s'", deck_slot)
                raise ValueError(f"No labware loaded in deck slot '{deck_slot}'. Load labware before accessing wells.")
            well_pos = labware.get_well_position(well_name).get_xy()
            # the deck is rotated 90 degrees clockwise for this machine
            pos += well_pos.swap_xy()
            # get z
            pos += Position(z=labware.get_height() - self.CEILING_HEIGHT)
            # if tip attached, add tip length
            if self.pipette.is_tip_attached():
                pos += Position(z=self.TIP_LENGTH)
            self._logger.debug("Absolute Z position for deck slot '%s', well '%s': %s", deck_slot, well_name, pos)
        else:
            self._logger.debug("Absolute Z position for deck slot '%s': %s", deck_slot, pos)
        return pos
    
    ### Control (immediate commands) ###
    
    def pause(self):
        """
        Pause the execution of queued commands.
        """
        print("Pausing machine")
    
    def resume(self):
        """
        Resume the execution of queued commands.
        """
        print("Resuming machine")

    def cancel(self):
        """
        Cancel the execution of queued commands.
        """
        print("Cancelling machine")