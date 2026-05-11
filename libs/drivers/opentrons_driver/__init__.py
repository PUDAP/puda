"""opentrons-driver — pure Python driver for the Opentrons OT-2 robot.

Quick start::

    from opentrons_driver.machines import OT2

    robot = OT2(robot_ip="192.168.50.64")
    print(robot.is_connected())
    result = robot.upload_and_run(open("my_protocol.py").read())
    print(result["run_status"])
"""

from opentrons_driver.machines.ot2 import OT2
from opentrons_driver.controllers.protocol import Protocol, ProtocolCommand
from opentrons_driver.core.http_client import OT2HttpClient
from opentrons_driver.core.logging import setup_logging
__version__ = "0.1.0"

__all__ = [
    "OT2",
    "Protocol",
    "ProtocolCommand",
    "OT2HttpClient",
    "setup_logging",
    "__version__",
]
