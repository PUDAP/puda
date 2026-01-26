"""
G-code controller for motion systems.

This module provides a Python interface for controlling G-code compatible motion
systems (e.g., QuBot) via serial communication. All movements are executed in
absolute coordinates, with relative moves converted to absolute internally.
Supports homing and position synchronization.
"""

import re
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, Union

from puda_drivers.core.serialcontroller import SerialController
from puda_drivers.core.position import Position


@dataclass
class AxisLimits:
    """Holds min/max limits for an axis."""

    min: float
    max: float

    def validate(self, value: float) -> None:
        """
        Validate that a value is within the axis limits.

        Args:
            value: Value to validate

        Raises:
            ValueError: If value is outside the limits
        """
        if not (self.min <= value <= self.max):
            raise ValueError(
                f"Value {value} outside axis limits [{self.min}, {self.max}]"
            )


class GCodeController(SerialController):
    """
    Controller for G-code compatible motion systems.

    This class provides methods for controlling multi-axis motion systems that
    understand G-code commands. All movements are executed in absolute coordinates,
    with relative moves converted to absolute internally. Supports homing and
    position synchronization.

    Attributes:
        DEFAULT_FEEDRATE: Default feed rate in mm/min (3000)
        MAX_FEEDRATE: Maximum allowed feed rate in mm/min (3000)
        TOLERANCE: Position synchronization tolerance in mm (0.01)
    """

    DEFAULT_FEEDRATE = 3000  # mm/min
    MAX_FEEDRATE = 3000  # mm/min
    MAX_Z_FEED_RATE = 1000 # mm/min
    TOLERANCE = 0.01  # tolerance for position sync in mm
    SAFE_MOVE_HEIGHT = -5 # safe height for Z and A axes in mm

    PROTOCOL_TERMINATOR = "\r"
    VALID_AXES = "XYZA"

    def __init__(
        self,
        port_name: Optional[str] = None,
        baudrate: int = SerialController.DEFAULT_BAUDRATE,
        timeout: int = SerialController.DEFAULT_TIMEOUT,
        feed: int = DEFAULT_FEEDRATE,
        z_feed: int = MAX_Z_FEED_RATE,
    ):
        """
        Initialize the G-code controller.

        Args:
            port_name: Serial port name (e.g., '/dev/ttyACM0' or 'COM3')
            baudrate: Baud rate for serial communication. Defaults to 9600.
            timeout: Timeout in seconds for operations. Defaults to 20.
            feed: Initial feed rate in mm/min. Defaults to 3000.
        """
        super().__init__(port_name, baudrate, timeout)

        self._logger = logging.getLogger(__name__)
        self._logger.info(
            "GCodeController initialized with port='%s', baudrate=%s, timeout=%s",
            port_name,
            baudrate,
            timeout,
        )

        # Tracks internal position state
        self._current_position = Position(x=0.0, y=0.0, z=0.0, a=0.0)
        self._feed: int = feed
        self._z_feed: int = z_feed

        # Initialize axis limits with default values
        self._axis_limits: Dict[str, AxisLimits] = {
            "X": AxisLimits(0, 0),
            "Y": AxisLimits(0, 0),
            "Z": AxisLimits(0, 0),
            "A": AxisLimits(0, 0),
        }

    @property
    def feed(self) -> int:
        """Get the current feed rate in mm/min."""
        return self._feed

    @feed.setter
    def feed(self, new_feed: int) -> None:
        """
        Set the movement feed rate, enforcing the maximum limit.

        Args:
            new_feed: New feed rate in mm/min (must be > 0)

        Raises:
            ValueError: If feed rate is not positive
        """
        if new_feed <= 0:
            error_msg = (
                f"Attempted to set invalid feed rate: {new_feed}. Must be > 0."
            )
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        if new_feed > self.MAX_FEEDRATE:
            self._logger.warning(
                "Requested feed rate (%s) exceeds maximum (%s). "
                "Setting feed rate to maximum: %s.",
                new_feed,
                self.MAX_FEEDRATE,
                self.MAX_FEEDRATE,
            )
            self._feed = self.MAX_FEEDRATE
        else:
            self._feed = new_feed
            self._logger.debug("Feed rate set to: %s mm/min.", self._feed)

    def _build_command(self, command: str, value: Optional[str] = None) -> str:
        """
        Build a G-code command with terminator.

        Args:
            command: G-code command string (without terminator)

        Returns:
            Complete command string with terminator
        """
        return f"{command}{self.PROTOCOL_TERMINATOR}"

    def _wait_for_move(self) -> None:
        """
        Wait for the current move to complete (M400 command).
        
        This sends the M400 command which waits for all moves in the queue to complete
        before continuing. This ensures that position updates are accurate.
        """
        self.execute("M400")

    def _validate_axis(self, axis: str) -> str:
        """
        Validate and normalize an axis name.

        Args:
            axis: Axis name to validate

        Returns:
            Uppercase axis name

        Raises:
            ValueError: If axis is not valid
        """
        axis_upper = axis.upper()
        if axis_upper not in self.VALID_AXES:
            self._logger.error(
                "Invalid axis '%s' provided. Must be one of: %s.",
                axis_upper,
                ", ".join(self.VALID_AXES),
            )
            raise ValueError(
                f"Invalid axis. Must be one of: {', '.join(self.VALID_AXES)}."
            )
        return axis_upper

    def _validate_move_positions(
        self,
        position: Position,
    ) -> None:
        """
        Validate that move positions are within axis limits.

        Only validates axes that are present in the position. Raises ValueError
        if any position is outside the configured limits.

        Args:
            position: Position object to validate

        Raises:
            ValueError: If any position is outside the axis limits
        """
        if position.has_axis("x"):
            if "X" in self._axis_limits:
                try:
                    self._axis_limits["X"].validate(position.x)
                except ValueError as e:
                    self._logger.error("Move validation failed for X axis: %s", e)
                    raise
        if position.has_axis("y"):
            if "Y" in self._axis_limits:
                try:
                    self._axis_limits["Y"].validate(position.y)
                except ValueError as e:
                    self._logger.error("Move validation failed for Y axis: %s", e)
                    raise
        if position.has_axis("z"):
            if "Z" in self._axis_limits:
                try:
                    self._axis_limits["Z"].validate(position.z)
                except ValueError as e:
                    self._logger.error("Move validation failed for Z axis: %s", e)
                    raise
        if position.has_axis("a"):
            if "A" in self._axis_limits:
                try:
                    self._axis_limits["A"].validate(position.a)
                except ValueError as e:
                    self._logger.error("Move validation failed for A axis: %s", e)
                    raise

    def set_axis_limits(
        self, axis: str, min_val: float, max_val: float
    ) -> None:
        """
        Set the min/max limits for an axis.

        Args:
            axis: Axis name ('X', 'Y', 'Z', 'A')
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Raises:
            ValueError: If axis is unknown or min >= max
        """
        axis = self._validate_axis(axis)

        if min_val >= max_val:
            raise ValueError("min must be < max")

        self._axis_limits[axis] = AxisLimits(min_val, max_val)
        self._logger.info(
            "Set limits for axis %s: [%s, %s]", axis, min_val, max_val
        )

    def get_axis_limits(
        self, axis: Optional[str] = None
    ) -> Union[AxisLimits, Dict[str, AxisLimits]]:
        """
        Get the current limits for an axis or all axes.

        Args:
            axis: Optional axis name ('X', 'Y', 'Z', 'A'). If None, returns all limits.

        Returns:
            If axis is specified: AxisLimits object with min and max values.
            If axis is None: Dictionary of all axis limits.

        Raises:
            ValueError: If axis is unknown (only when axis is provided)
        """
        if axis is None:
            return self._axis_limits.copy()
        axis = self._validate_axis(axis)
        return self._axis_limits[axis]

    def home(self, axis: Optional[str] = None) -> None:
        """
        Home one or all axes (G28 command).

        Args:
            axis: Optional axis to home ('X', 'Y', 'Z', 'A').
                  If None, homes all axes.

        Raises:
            ValueError: If an invalid axis is provided
        """
        if axis:
            axis = self._validate_axis(axis)
            cmd = f"G28 {axis}"
            home_target = axis
        else:
            cmd = "G28"
            home_target = "All"

        self._logger.info("[%s] homing axis/axes: %s **", cmd, home_target)
        self.execute(command=cmd, timeout=90) # 90 seconds timeout for homing
        self._logger.info("Homing of %s completed.\n", home_target)

        # Update internal position (optimistic zeroing)
        if axis:
            self._current_position[axis.lower()] = 0.0
        else:
            self._current_position = Position(x=0.0, y=0.0, z=0.0, a=0.0)

        self._logger.debug(
            "Internal position updated (optimistically zeroed) to %s",
            self._current_position,
        )

    def move_absolute(
        self,
        position: Position,
        feed: Optional[int] = None,
    ) -> Position:
        """
        Move to an absolute position (G90 + G1 command).

        Args:
            position: Target Position object. Missing axes will use current position values.
            feed: Feed rate for this move (optional, uses current feed if not specified)

        Raises:
            ValueError: If any position is outside the axis limits

        Examples:
            >>> pos = Position(x=10, y=20, z=30)
            >>> controller.move_absolute(position=pos)
            >>> # Partial position (only x and y specified)
            >>> pos = Position(x=10, y=20)
            >>> controller.move_absolute(position=pos)  # z and a use current values
        """
        # Validate positions before executing move
        self._validate_move_positions(position=position)

        feed_rate = feed if feed is not None else self._feed
        self._logger.info(
            "Preparing absolute move to X:%s, Y:%s, Z:%s, A:%s at F:%s",
            position.x,
            position.y,
            position.z,
            position.a,
            feed_rate,
        )

        return self._execute_move(
            position=position,
            feed=feed_rate
        )

    def move_relative(
        self,
        position: Position,
        feed: Optional[int] = None,
    ) -> Position:
        """
        Move relative to the current position (converted to absolute move internally).

        Args:
            position: Relative Position object. Only axes specified in position will move.
            feed: Feed rate for this move (optional, uses current feed if not specified)

        Raises:
            ValueError: If any resulting absolute position is outside the axis limits

        Examples:
            >>> # Move relative in x and y only
            >>> pos = Position(x=10, y=20)
            >>> controller.move_relative(position=pos)
            >>> # Move relative in all axes
            >>> pos = Position(x=10, y=20, z=5, a=0)
            >>> controller.move_relative(position=pos)
        """
        # Convert relative movements to absolute positions
        # Only move axes that are specified in the position
        abs_x = self._current_position.x
        abs_y = self._current_position.y
        abs_z = self._current_position.z
        abs_a = self._current_position.a

        if position.has_axis("x"):
            abs_x = self._current_position.x + position.x
        if position.has_axis("y"):
            abs_y = self._current_position.y + position.y
        if position.has_axis("z"):
            abs_z = self._current_position.z + position.z
        if position.has_axis("a"):
            abs_a = self._current_position.a + position.a

        # Create absolute position for validation and execution
        abs_position = Position(x=abs_x, y=abs_y, z=abs_z, a=abs_a)
        
        # Validate absolute positions before executing move
        self._validate_move_positions(position=abs_position)

        feed_rate = feed if feed is not None else self._feed
        self._logger.info(
            "Preparing relative move by dX:%s, dY:%s, dZ:%s, dA:%s at F:%s",
            position.x if position.has_axis("x") else 0,
            position.y if position.has_axis("y") else 0,
            position.z if position.has_axis("z") else 0,
            position.a if position.has_axis("a") else 0,
            feed_rate,
        )

        return self._execute_move(
            position=abs_position,
            feed=feed_rate
        )

    def _execute_move(
        self,
        position: Position,
        feed: int,
    ) -> Position:
        """
        Internal helper for executing G1 move commands with safe movement pattern.
        All coordinates are treated as absolute positions.

        Safe move pattern:
        1. If X or Y movement is needed, first move Z and A to safe height
        2. Then move X, Y to target
        3. Finally move Z or A to target (only the one that needs to move, the other stays where it is)

        Args:
            position: Position with absolute positions for X, Y, Z, A axes
            feed: Feed rate for the move
        """
        # Check if any movement is needed
        needs_x_move = abs(position.x - self._current_position.x) > self.TOLERANCE
        needs_y_move = abs(position.y - self._current_position.y) > self.TOLERANCE
        needs_z_move = abs(position.z - 0) > self.TOLERANCE
        needs_a_move = abs(position.a - 0) > self.TOLERANCE
        
        if not (needs_x_move or needs_y_move or needs_z_move or needs_a_move):
            self._logger.warning(
                "Move command issued without any axis movement. Skipping transmission."
            )
            return
        
        if needs_z_move and needs_a_move:
            self._logger.error(
                "Move command issued with both Z and A movement. This is not supported. Skipping transmission."
            )
            raise ValueError("Move command issued with both Z and A movement. This is not supported.")

        # Step 0: Ensure absolute mode is active
        self.execute("G90")

        # Step 1: Move Z and A to SAFE_MOVE_HEIGHT if XY movement is needed
        if needs_x_move or needs_y_move:
            self._logger.debug(
                "Safe move: Raising Z and A to safe height (%s) before XY movement", self.SAFE_MOVE_HEIGHT
            )
            move_cmd = f"G1 Z{self.SAFE_MOVE_HEIGHT} A{self.SAFE_MOVE_HEIGHT} F{self._z_feed}"
            self.execute(move_cmd)
            self._wait_for_move()
            self._current_position.z = self.SAFE_MOVE_HEIGHT
            self._current_position.a = self.SAFE_MOVE_HEIGHT
            self._logger.debug("Z and A moved to safe height (%s)", self.SAFE_MOVE_HEIGHT)

            # update needs_z_move and needs_a_move based on the current position
            needs_z_move = abs(position.z - self._current_position.z) > self.TOLERANCE
            needs_a_move = abs(position.a - self._current_position.a) > self.TOLERANCE

        # Step 2: Move X, Y to target
        if needs_x_move or needs_y_move:
            move_cmd = "G1"
            if needs_x_move:
                move_cmd += f" X{position.x}"
            if needs_y_move:
                move_cmd += f" Y{position.y}"
            move_cmd += f" F{feed}"

            self._logger.debug("Executing XY move command: %s", move_cmd)
            self.execute(move_cmd)
            self._wait_for_move()

            # Update position for moved axes
            if needs_x_move:
                self._current_position.x = position.x
            if needs_y_move:
                self._current_position.y = position.y

        # Step 3: Move Z or A to target (only the one that needs to move)
        if needs_z_move:
            move_cmd = f"G1 Z{position.z} F{self._z_feed}"
            self.execute(move_cmd)
            self._wait_for_move()
            self._current_position.z = position.z
        if needs_a_move:
            move_cmd = f"G1 A{position.a} F{self._z_feed}"
            self.execute(move_cmd)
            self._wait_for_move()
            self._current_position.a = position.a
        self._logger.debug("New internal position: %s", self._current_position)
        
        return self._current_position

    async def get_position(self) -> Position:
        """
        Get the current machine position (M114 command) asynchronously.

        This method can be called even when the machine is moving from other commands,
        as it runs the blocking serial communication in a separate thread.
        
        If the M114 command takes more than 1 second to respond, falls back to
        returning the internally tracked position instead.

        Returns:
            Position containing X, Y, Z, and A positions

        Note:
            Returns an empty Position if the query fails or no positions are found.
        """
        self._logger.info("Querying current machine position (M114).")
        # Run the blocking execute call in a thread pool to allow concurrent operations
        # with a 1 second timeout - if it takes longer, fall back to internal position
        try:
            res: str = await asyncio.wait_for(
                asyncio.to_thread(self.execute, "M114"),
                timeout=1.0
            )
            
            # Extract position values using regex
            pattern = re.compile(r"([XYZA]):(-?\d+\.\d+)")
            matches = pattern.findall(res)

            position_data: Dict[str, float] = {}

            for axis, value_str in matches:
                try:
                    position_data[axis.lower()] = float(value_str)
                except ValueError:
                    self._logger.error(
                        "Failed to convert position value '%s' for axis %s to float.",
                        value_str,
                        axis,
                    )
                    continue

            position = Position.from_dict(position_data)
            self._logger.info("Query position complete. Retrieved positions: %s", position)
            return position
        except asyncio.TimeoutError:
            self._logger.info(
                "M114 command timed out after 1 second. Falling back to internal position."
            )
            return self.get_internal_position()

    def _sync_position(self) -> Tuple[bool, Position]:
        """
        Synchronize internal position with actual machine position.

        Queries the machine position and compares it with the internal position.
        If a discrepancy greater than the tolerance is found, attempts to correct
        it by moving to the internal position.

        Returns:
            Tuple of (adjustment_occurred: bool, final_position: Position)
            where adjustment_occurred is True if a correction move was made.

        Note:
            This method may recursively call itself if a correction move is made.
            Since this method calls move_absolute (which is blocking), it remains
            synchronous. The async get_position() is called using asyncio.run().
        """
        self._logger.info("Starting position synchronization check (M114).")

        # Query the actual machine position (async method called from sync context)
        queried_position = asyncio.run(self.get_position())

        if not queried_position.get_axes():
            self._logger.error("Query position failed. Cannot synchronize.")
            raise ValueError("Query position failed. Cannot synchronize.")

        # Compare internal vs. queried position
        axis_keys = ["x", "y", "z", "a"]
        adjustment_needed = False

        for axis in axis_keys:
            axis_upper = axis.upper()
            if (
                self._current_position.has_axis(axis)
                and queried_position.has_axis(axis)
                and abs(self._current_position[axis] - queried_position[axis])
                > self.TOLERANCE
            ):
                self._logger.warning(
                    "Position mismatch found on %s axis: Internal=%.3f, Queried=%.3f",
                    axis_upper,
                    self._current_position[axis],
                    queried_position[axis],
                )
                adjustment_needed = True
            elif queried_position.has_axis(axis):
                # Update internal position with queried position if it differs slightly
                self._current_position[axis] = queried_position[axis]

        # Perform re-synchronization move if needed
        if adjustment_needed:
            self._logger.info(
                "** DISCREPANCY DETECTED. Moving robot to internal position: %s **",
                self._current_position,
            )

            try:
                self.move_absolute(position=self._current_position.copy())
                self._logger.info("Synchronization move successfully completed.")

                # Recursive call to verify position after move
                return self._sync_position()
            except (ValueError, RuntimeError, OSError) as e:
                self._logger.error("Synchronization move failed: %s", e)
                adjustment_needed = False

        if adjustment_needed:
            self._logger.info(
                "Position check complete. Internal position is synchronized with machine."
            )
        else:
            self._logger.info("No adjustment was made.")

        return adjustment_needed, self._current_position.copy()

    def get_info(self) -> str:
        """
        Query machine information (M115 command).

        Returns:
            Machine information string from the device
        """
        self._logger.info("Querying machine information (M115).")
        return self.execute("M115")

    def get_internal_position(self) -> Position:
        """
        Get the internally tracked position.

        Returns:
            Position containing the current internal position for all axes
        """
        self._logger.debug("Returning internal position: %s", self._current_position)
        return self._current_position.copy()