"""
Main entry point for the Biologic machine edge service.

This module provides the main event loop for the Biologic machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
import sys
from puda_drivers.machines import Biologic
from puda_comms import EdgeNatsClient, EdgeRunner
from pydantic import IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict

class Config(BaseSettings):
    machine_id: str
    nats_servers: str
    biologic_ip: IPvAnyAddress
    
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
    try:
        config = Config()
    except Exception as e:
        logger.error("Failed to load configuration: %s", e, exc_info=True)
        sys.exit(1)
    logger.info("Config loaded: machine_id=%s, biologic_ip=%s", config.machine_id, config.biologic_ip)

    logger.info("Initializing machine driver")
    driver = Biologic(device_ip=str(config.biologic_ip))
    driver.startup()
    logger.info("Biologic device connected and ready")

    logger.info("Connecting to NATS at %s", config.nats_servers)
    nats_server_list = [s.strip() for s in config.nats_servers.split(",") if s.strip()]
    edge_nats_client = EdgeNatsClient(
        servers=nats_server_list,
        machine_id=config.machine_id,
    )

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