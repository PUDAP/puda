"""
Main entry point for the First machine edge service.

This module provides the main event loop for the First machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from puda_drivers.machines import First
from puda_comms import EdgeNatsClient, EdgeRunner

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("puda_drivers").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main():
    logger.info("=== Starting First machine edge service ===")

    machine_id = os.getenv("MACHINE_ID")
    if not machine_id:
        raise ValueError("MACHINE_ID environment variable is required")
    nats_servers_env = os.getenv("NATS_SERVERS")
    if not nats_servers_env:
        raise ValueError("NATS_SERVERS environment variable is required")
    nats_servers = [s.strip() for s in nats_servers_env.split(",")]
    qubot_port = os.getenv("QUBOT_PORT")
    if not qubot_port:
        raise ValueError("QUBOT_PORT environment variable is required")
    sartorius_port = os.getenv("SARTORIUS_PORT")
    if not sartorius_port:
        raise ValueError("SARTORIUS_PORT environment variable is required")
    camera_index_str = os.getenv("CAMERA_INDEX")
    if not camera_index_str:
        raise ValueError("CAMERA_INDEX environment variable is required")
    camera_index = int(camera_index_str)

    logger.info(
        "Initializing First machine with qubot_port: %s, sartorius_port: %s, camera_index: %s",
        qubot_port,
        sartorius_port,
        camera_index,
    )
    driver = First(
        qubot_port=qubot_port,
        sartorius_port=sartorius_port,
        camera_index=camera_index,
    )
    driver.startup()
    logger.info("First machine initialized successfully")

    logger.info("Initializing NATS client with servers: %s", nats_servers)
    edge_nats_client = EdgeNatsClient(servers=nats_servers, machine_id=machine_id)

    async def telemetry_tick():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_position(await driver.get_position())
        await edge_nats_client.publish_health({"cpu": 45.2, "mem": 60.1, "temp": 35.0})

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_tick=telemetry_tick,
        state_payload_fn=lambda: {"deck": driver.deck.to_dict()},
    )
    await runner.connect()
    logger.info("==================== first-edge ready to accept messages ====================")
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
