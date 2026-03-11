"""
Main entry point for the Biologic machine edge service.

This module provides the main event loop for the Biologic machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
import sys
import time
from puda_drivers.machines import Biologic
from puda_comms import EdgeNatsClient, EdgeRunner
from pydantic import IPvAnyAddress
from pydantic_settings import BaseSettings, SettingsConfigDict


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logging.getLogger("puda_drivers").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Environment configuration
class Config(BaseSettings):
    machine_id: str
    nats_servers: str
    biologic_ip: IPvAnyAddress

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def nats_server_list(self) -> list[str]:
        return [s.strip() for s in self.nats_servers.split(",") if s.strip()]

def load_config() -> Config:
    """Load and validate configuration; exit process on failure."""
    try:
        return Config()
    except Exception as e:
        logger.error("Failed to load configuration: %s", e, exc_info=True)
        sys.exit(1)


async def main():
    """Initialize the Biologic machine driver and NATS client, then run the edge runner."""
    config = load_config()
    logger.info(
        "Config: machine_id=%s, biologic_ip=%s",
        config.machine_id, config.biologic_ip,
    )

    logger.info("Initializing machine driver")
    driver = Biologic(device_ip=str(config.biologic_ip))
    driver.startup()
    logger.info("Biologic machine initialized successfully")

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_server_list,
        machine_id=config.machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_health({"cpu": 45.2, "mem": 60.1, "temp": 35.0})

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
        state_handler=lambda: {},
    )
    await runner.connect()
    logger.info("NATS client initialized successfully")
    logger.info(
        "==================== %s Edge Service Ready. Publishing telemetry... ====================",
        config.machine_id,
    )
    await runner.run()


# Run main in a loop; retry on fatal errors, ignore KeyboardInterrupt.
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
