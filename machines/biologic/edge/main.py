"""
Main entry point for the Biologic machine edge service.

This module provides the main event loop for the Biologic machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
from puda_drivers.machines import Biologic
from puda_comms import EdgeNatsClient, EdgeRunner
from pydantic import Field, IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict

class Config(BaseSettings):
    machine_id: str = Field(description="Machine identifier")
    nats_servers: list[str]
    biologic_ip: IPvAnyAddress

    # Configuration to handle case-sensitivity and env files
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("puda_drivers").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Loading configuration from environment")
    config = Config()
    logger.info("Config loaded: machine_id=%s, biologic_ip=%s", config.machine_id, config.biologic_ip)

    logger.info("Connecting to Biologic device at %s", config.biologic_ip)
    driver = Biologic(device_ip=config.biologic_ip)
    driver.startup()
    logger.info("Biologic device connected and ready")

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(servers=config.nats_servers, machine_id=config.machine_id)

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_health({"cpu": 45.2, "mem": 60.1, "temp": 35.0})

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
    )
    await runner.connect()
    logger.info("NATS client connected")
    logger.info(
        "==================== %s Edge Service ready. Publishing telemetry... ====================",
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