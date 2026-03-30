"""
OT-2 Edge Service

Bridges the Opentrons OT-2 HTTP API to the PUDA NATS bus.
Follows the same pattern as the qubot 'first' machine edge service.

Commands are received on  puda.{machine_id}.commands.queue
Responses are published on puda.{machine_id}.commands.response
Telemetry is published on  puda.{machine_id}.telemetry.*
"""
import asyncio
import logging
import sys
import time

from pydantic_settings import BaseSettings, SettingsConfigDict
from puda_comms import EdgeNatsClient, EdgeRunner

from opentrons_driver.machines import OT2
from opentrons_driver.core.logging import setup_logging

setup_logging(log_level=logging.INFO)
logging.getLogger("opentrons_driver").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class Config(BaseSettings):
    machine_id: str
    nats_servers: str
    robot_ip: str
    robot_port: int = 31950

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def nats_server_list(self) -> list[str]:
        return [s.strip() for s in self.nats_servers.split(",") if s.strip()]


def load_config() -> Config:
    try:
        return Config()
    except Exception as e:
        logger.error("Failed to load configuration: %s", e, exc_info=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# OT-2 command adapter
#
# EdgeRunner dispatches by calling driver.execute_command(name, params).
# Each cmd_* method maps one NATS command name to an OT2 driver call.
# ---------------------------------------------------------------------------

class OT2EdgeDriver:
    """Adapter that maps NATS command names to OT2 driver calls."""

    def __init__(self, robot: OT2) -> None:
        self._robot = robot

    def execute_command(self, name: str, params: dict) -> dict:
        handler = getattr(self, f"cmd_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown command: {name!r}")
        return handler(params)

    # ------------------------------------------------------------------
    # Protocol execution
    # ------------------------------------------------------------------

    def cmd_run_protocol(self, params: dict) -> dict:
        """Upload and run a protocol.

        Params:
            code (str):            Python protocol source code.
            filename (str):        Filename shown in run history (default: protocol.py).
            wait (bool):           Block until complete (default: True).
            max_wait (int):        Timeout in seconds (default: 300).
        """
        return self._robot.upload_and_run(
            code=params["code"],
            filename=params.get("filename", "protocol.py"),
            wait=params.get("wait", True),
            max_wait=params.get("max_wait", 300),
        )

    # ------------------------------------------------------------------
    # Run control
    # ------------------------------------------------------------------

    def cmd_get_status(self, params: dict) -> dict:
        """Get run status.

        Params:
            run_id (str, optional): Specific run ID; omit for latest run.
        """
        return self._robot.get_status(run_id=params.get("run_id"))

    def cmd_pause(self, params: dict) -> dict:
        """Pause the current run.

        Params:
            run_id (str): Run ID to pause.
        """
        run_id = params["run_id"]
        return {"paused": self._robot.pause(run_id), "run_id": run_id}

    def cmd_resume(self, params: dict) -> dict:
        """Resume a paused run.

        Params:
            run_id (str): Run ID to resume.
        """
        run_id = params["run_id"]
        return {"resumed": self._robot.resume(run_id), "run_id": run_id}

    def cmd_stop(self, params: dict) -> dict:
        """Stop (cancel) a run.

        Params:
            run_id (str): Run ID to stop.
        """
        run_id = params["run_id"]
        return {"stopped": self._robot.stop(run_id), "run_id": run_id}

    # ------------------------------------------------------------------
    # Labware
    # ------------------------------------------------------------------

    def cmd_upload_labware(self, params: dict) -> dict:
        """Upload a custom labware definition to the robot.

        Params:
            labware (dict): Full Opentrons labware JSON definition.
        """
        return self._robot.upload_labware(params["labware"])

    # ------------------------------------------------------------------
    # Health / telemetry helpers
    # ------------------------------------------------------------------

    def cmd_is_connected(self, params: dict) -> dict:
        return {"connected": self._robot.is_connected()}

    def get_health(self) -> dict:
        return {
            "connected": self._robot.is_connected(),
            "robot_ip": self._robot.client.robot_ip,
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    config = load_config()
    logger.info("Config loaded: machine_id=%s robot_ip=%s", config.machine_id, config.robot_ip)
    logger.info("Full config: %s", config.model_dump())

    logger.info("Initializing OT-2 driver")
    robot = OT2(robot_ip=config.robot_ip, port=config.robot_port)
    if not robot.is_connected():
        logger.warning("OT-2 at %s is not reachable — edge will still start", config.robot_ip)
    else:
        logger.info("OT-2 connected at %s:%s", config.robot_ip, config.robot_port)

    driver = OT2EdgeDriver(robot)

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_server_list,
        machine_id=config.machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_health(driver.get_health())

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
        state_handler=lambda: {"robot_ip": config.robot_ip},
    )

    await runner.connect()
    logger.info(
        "==================== %s Edge Service Ready. Publishing telemetry... ====================",
        config.machine_id,
    )
    await runner.run()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.warning("Received KeyboardInterrupt, but continuing to run...")
            time.sleep(1)
        except Exception as e:
            logger.error("Fatal error: %s", e, exc_info=True)
            time.sleep(5)
