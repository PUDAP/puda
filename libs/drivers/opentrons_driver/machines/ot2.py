"""High-level Opentrons OT-2 machine interface.

The :class:`OT2` class is the primary entry-point for this package.  It
mirrors the pattern of the ``First`` machine in ``puda-drivers``: a single
object that wires together the underlying controllers and exposes a clean,
intent-oriented API.

Example::

    from opentrons_driver.machines import OT2
    from opentrons_driver.core.logging import setup_logging
    import logging

    setup_logging(enable_file_logging=True, log_level=logging.INFO)

    robot = OT2(robot_ip="192.168.50.64")

    if not robot.is_connected():
        raise RuntimeError("Robot is unreachable")

    # Build a protocol via the model API
    from opentrons_driver.controllers.protocol import Protocol, ProtocolCommand

    protocol = Protocol(
        protocol_name="Simple Transfer",
        author="Lab",
        description="Transfer 100 µL from A1 to B1",
        robot_type="OT-2",
        api_level="2.23",
        commands=[...],
    )

    result = robot.upload_and_run(protocol.to_python_code(), wait=True)
    print(result["run_status"])   # "succeeded"
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from opentrons_driver.controllers import resources as resources_ctrl
from opentrons_driver.controllers import run as run_ctrl
from opentrons_driver.controllers.protocol import upload_protocol
from opentrons_driver.core.http_client import DEFAULT_ROBOT_IP, OT2HttpClient

logger = logging.getLogger(__name__)


class OT2:
    """Opentrons OT-2 robot driver.

    Args:
        robot_ip: IPv4 address of the robot on the local network.
            Defaults to ``"192.168.50.64"``.
        port: HTTP port (default ``31950``).
        timeout: Default HTTP timeout in seconds (default ``10``).

    Attributes:
        client: The underlying :class:`~opentrons_driver.core.http_client.OT2HttpClient`.
    """

    def __init__(
        self,
        robot_ip: str = DEFAULT_ROBOT_IP,
        port: int = 31950,
        timeout: int = 10,
    ) -> None:
        self.client = OT2HttpClient(robot_ip=robot_ip, port=port, timeout=timeout)
        logger.info("OT2 driver initialised (ip=%s port=%s)", robot_ip, port)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if the robot is reachable via ``GET /health``."""
        return self.client.is_connected()

    # ------------------------------------------------------------------
    # Protocol upload and run
    # ------------------------------------------------------------------

    def upload_and_run(
        self,
        code: str,
        filename: str = "protocol.py",
        wait: bool = True,
        max_wait: int = 300,
        poll_interval: int = 3,
    ) -> dict:
        """Upload a protocol and start it on the robot.

        Args:
            code: Python protocol source code.  Markdown fences and minor
                indentation issues are corrected automatically before upload.
            filename: Filename reported to the robot (used in run history).
            wait: If ``True`` (default), block until the run reaches a
                terminal state or *max_wait* seconds elapse.  If ``False``,
                return immediately after the run is started.
            max_wait: Maximum seconds to wait when *wait* is ``True``.
            poll_interval: Poll interval in seconds when *wait* is ``True``.

        Returns:
            When *wait* is ``True``: the status dict from
            :func:`~opentrons_driver.controllers.run.wait_for_completion`.

            When *wait* is ``False``: a dict with ``run_id``, ``protocol_id``,
            and ``run_status = "started"``.

        Raises:
            RuntimeError: If upload or run creation fails.
        """
        protocol_id = upload_protocol(self.client, code, filename)
        run_id = run_ctrl.create_run(self.client, protocol_id)

        if not run_ctrl.play_run(self.client, run_id):
            raise RuntimeError(f"Failed to start run {run_id}")

        if not wait:
            logger.info("Run %s started (non-blocking)", run_id)
            return {
                "run_id": run_id,
                "protocol_id": protocol_id,
                "run_status": "started",
                "robot_ip": self.client.robot_ip,
            }

        return run_ctrl.wait_for_completion(
            self.client, run_id, max_wait=max_wait, poll_interval=poll_interval
        )

    # ------------------------------------------------------------------
    # Run control
    # ------------------------------------------------------------------

    def get_status(self, run_id: Optional[str] = None) -> dict:
        """Retrieve the status of a run.

        Args:
            run_id: Specific run ID.  When ``None`` the most recent run is
                returned.

        Returns:
            Status dict — see
            :func:`~opentrons_driver.controllers.run.get_run_status`.
        """
        return run_ctrl.get_run_status(self.client, run_id)

    def pause(self, run_id: str) -> bool:
        """Pause a running protocol.

        Returns:
            ``True`` on success.
        """
        return run_ctrl.pause_run(self.client, run_id)

    def resume(self, run_id: str) -> bool:
        """Resume a paused protocol.

        Returns:
            ``True`` on success.
        """
        return run_ctrl.play_run(self.client, run_id)

    def stop(self, run_id: str) -> bool:
        """Stop (cancel) a run.

        Returns:
            ``True`` on success.
        """
        return run_ctrl.stop_run(self.client, run_id)

    # ------------------------------------------------------------------
    # Labware
    # ------------------------------------------------------------------

    def upload_labware(self, labware: Union[dict, str, Path]) -> dict:
        """Upload a custom labware definition to the robot.

        Args:
            labware: A labware definition ``dict``, or a path to a JSON file.

        Returns:
            Upload result dict — see
            :func:`~opentrons_driver.controllers.resources.upload_custom_labware`.
        """
        return resources_ctrl.upload_custom_labware(self.client, labware)

    # ------------------------------------------------------------------
    # Resource catalogues (no robot connection required)
    # ------------------------------------------------------------------

    def get_labware_types(self) -> list[str]:
        """Return a list of known labware load-names."""
        return resources_ctrl.get_labware_types()

    def get_pipette_types(self) -> list[str]:
        """Return a list of known pipette instrument names."""
        return resources_ctrl.get_pipette_types()
