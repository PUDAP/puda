"""
Main entry point for the Biologic machine edge service.

This module provides the main event loop for the Biologic machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from puda_drivers.machines import Biologic
from puda_comms import EdgeNatsClient, EdgeRunner

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("puda_drivers").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main():
    logger.info("=== Starting Biologic machine edge service ===")

    machine_id = os.getenv("MACHINE_ID")
    if not machine_id:
        raise ValueError("MACHINE_ID environment variable is required")
    nats_servers_env = os.getenv("NATS_SERVERS")
    if not nats_servers_env:
        raise ValueError("NATS_SERVERS environment variable is required")
    nats_servers = [s.strip() for s in nats_servers_env.split(",")]
    biologic_ip = os.getenv("BIOLOGIC_IP")
    if not biologic_ip:
        raise ValueError("BIOLOGIC_IP environment variable is required")

    logger.info("Initializing Biologic machine with IP: %s", biologic_ip)
    driver = Biologic(device_ip=biologic_ip)
    driver.startup()
    logger.info("Biologic machine initialized successfully")

    logger.info("Initializing NATS client with servers: %s", nats_servers)
    edge_nats_client = EdgeNatsClient(servers=nats_servers, machine_id=machine_id)

    async def telemetry_tick():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_health({"cpu": 45.2, "mem": 60.1, "temp": 35.0})

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_tick=telemetry_tick,
    )
    await runner.connect()
    logger.info("==================== biologic-edge ready to accept messages ====================")
    logger.info(
        "==================== Machine %s Ready. Publishing telemetry... ====================",
        machine_id,
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