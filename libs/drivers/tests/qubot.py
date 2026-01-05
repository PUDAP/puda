import logging
from puda_drivers.move import GCodeController
from puda_drivers.core import Position
from puda_drivers.core.logging import setup_logging

# Optinal: finding ports
# import serial.tools.list_ports
# for port, desc, hwid in serial.tools.list_ports.comports():
#     print(f"{port}: {desc} [{hwid}]")

# --- LOGGING CONFIGURATION ---
# All loggers in imported modules (SerialController, GCodeController) will inherit this setup.
setup_logging(
    enable_file_logging=True,
    log_level=logging.INFO,  # Use logging.DEBUG to see all (DEBUG, INFO, WARNING, ERROR, CRITICAL) logs
)

# OPTIONAL: If you only want GCodeController's logs at specific level, you can specifically set it here
# logging.getLogger('puda_drivers.gcodecontroller').setLevel(logging.INFO)

PORT_NAME = "/dev/ttyACM0"


def main():
    print("--- Starting GCode Controller Application ---")

    try:
        # Instantiate the qubot controller
        qubot = GCodeController(port_name=PORT_NAME)

        # Example: Set custom axis limits
        qubot.set_axis_limits("X", 0, 330)
        qubot.set_axis_limits("Y", -440, 0)
        qubot.set_axis_limits("Z", -175, 0)
        qubot.set_axis_limits("A", -175, 0)

        qubot.connect()

        # # Example: Get current axis limits
        # print("\n--- Current Axis Limits ---")
        # all_limits = qubot.get_axis_limits()
        # for axis, limits in all_limits.items():
        #     print(f"{axis}: [{limits.min}, {limits.max}]")

        # # Example: Get limits for a specific axis
        # x_limits = qubot.get_axis_limits("X")
        # print(f"\nX axis limits: [{x_limits.min}, {x_limits.max}]")

        # qubot.query_position()
        # Always start with homing
        qubot.home()

        # # Setting feed rate (aka move speed)
        # # Should generate WARNING due to exceeding MAX_FEEDRATE (3000)
        # qubot.feed = 5000

        # Relative moves are converted to absolute internally, but works the same
        # for anything in the -axis, will have to be moved individually, else error will be raised
        qubot.move_absolute(position=Position(x=0.0, y=-5.0, z=-175.0))

        # print("\n")
        # qubot.move_relative(x=10.0)

        # Example stepping code
        # for _ in range(10):
        #     pos = qubot.move_relative(x=10.0)
        #     print(f"Position: {pos}")

        # sync position is always called after move automatically (now private: _sync_position())
        # Position synchronization happens automatically after each move

        # qubot.move_absolute(x=330.0, y=-440.0, z=-175.0)
        # Position synchronization happens automatically after each move
        # Example of an ERROR - invalid axis
        # try:
        #     qubot.home(axis="B")  # Generates ERROR
        # except ValueError:
        #     pass

        # Example of an ERROR - position outside limits
        # This will raise ValueError because x=250 is outside the X limits [0, 200]
        # try:
        #     qubot.move_absolute(x=250.0)  # Raises ValueError if outside limits
        # except ValueError as e:
        #     print(f"Position validation error (expected): {e}")

        # Example of relative move that would exceed limits
        # This will raise ValueError if the resulting absolute position is outside limits
        # try:
        #     qubot.move_relative(x=300.0)  # If current X + 300 > 200, raises ValueError
        # except ValueError as e:
        #     print(f"Position validation error (expected): {e}")

        # Example of an ERROR - simultaneous Z and A movement
        # This will raise ValueError because Z and A cannot move at the same time
        # try:
        #     qubot.move_absolute(z=-10.0, a=-20.0)  # Raises ValueError if both Z and A are moved
        # except ValueError as e:
        #     print(f"Z/A simultaneous movement error (expected): {e}")

        qubot.disconnect()
        print("Disconnected from qubot")

    except Exception as e:
        logging.getLogger(__name__).error("An unrecoverable error occurred: %s", e)


if __name__ == "__main__":
    main()
