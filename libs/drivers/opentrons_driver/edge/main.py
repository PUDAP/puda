"""
OT-2 Edge Service

Bridges the Opentrons OT-2 HTTP API to the PUDA NATS bus.
Follows the same pattern as the qubot 'first' machine edge service.

The OT2 machine driver is passed directly to EdgeRunner, which dispatches
incoming NATS commands to OT2 methods by name:

    upload_and_run    – upload and run a protocol on the robot
    get_status        – retrieve current run status
    pause             – pause the active run
    resume            – resume a paused run
    stop              – stop (cancel) the active run
    upload_labware    – upload a custom labware definition
    is_connected      – check whether the robot HTTP API is reachable
    get_labware_types – list known labware load-names
    get_pipette_types – list known pipette instrument names
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
# Main
# ---------------------------------------------------------------------------

async def main():
    """Initialize the OT-2 driver and NATS client, then run the edge runner."""
    config = load_config()
    logger.info("Config loaded: machine_id=%s robot_ip=%s", config.machine_id, config.robot_ip)
    logger.info("Full config: %s", config.model_dump())

    logger.info("Initializing OT-2 driver")
    robot = OT2(robot_ip=config.robot_ip, port=config.robot_port)
    if not robot.is_connected():
        logger.warning("OT-2 at %s is not reachable — edge will still start", config.robot_ip)
    else:
        logger.info("OT-2 connected at %s:%s", config.robot_ip, config.robot_port)

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_server_list,
        machine_id=config.machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        connected = await asyncio.to_thread(robot.is_connected)
        await edge_nats_client.publish_health({
            "connected": connected,
            "robot_ip": config.robot_ip,
        })

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=robot,
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
