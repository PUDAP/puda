"""
Main entry point for the First machine edge service.

This module provides the main event loop for the First machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
from puda_drivers.machines import First
from puda_comms import EdgeNatsClient, EdgeRunner
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    machine_id: str = Field(description="Machine identifier")
    nats_servers: list[str]
    qubot_port: str
    sartorius_port: str
    camera_index: int

    # Configuration to handle case-sensitivity and env files
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("puda_drivers").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Loading configuration from environment for First machine")
    config = Config()
    logger.info(
        "Config loaded: machine_id=%s, qubot_port=%s, sartorius_port=%s, camera_index=%s",
        config.machine_id,
        config.qubot_port,
        config.sartorius_port,
        config.camera_index,
    )

    logger.info(
        "Initializing First machine with qubot_port: %s, sartorius_port: %s, camera_index: %s",
        config.qubot_port,
        config.sartorius_port,
        config.camera_index,
    )
    driver = First(
        qubot_port=config.qubot_port,
        sartorius_port=config.sartorius_port,
        camera_index=config.camera_index,
    )
    driver.startup()
    logger.info("First machine initialized successfully")

    logger.info("Initializing NATS client with servers: %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_servers,
        machine_id=config.machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_position(await driver.get_position())
        await edge_nats_client.publish_health({"cpu": 45.2, "mem": 60.1, "temp": 35.0})

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
        state_handler=lambda: {"deck": driver.deck.to_dict()},
    )
    await runner.connect()
    logger.info("NATS client initialized successfully")
    logger.info(
        "==================== %s Edge Service Ready. Publishing telemetry... ====================",
        config.machine_id,
    )
    await runner.run()


if __name__ == "__main__":
    import time

    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.warning("Received KeyboardInterrupt, but continuing to run...")
            time.sleep(1)
        except Exception as e:
            logger.error("Fatal error in main: %s", e, exc_info=True)
            time.sleep(5)
