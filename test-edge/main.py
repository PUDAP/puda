"""
Main entry point for the test-edge machine service.

Software-only simulator for local PUDA testing. One process runs one edge
with a single MACHINE_ID on NATS.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import logging
import sys
from pathlib import Path

import psutil
from pydantic_settings import BaseSettings, SettingsConfigDict
from puda import EdgeNatsClient, EdgeRunner

from driver import Driver

machine_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("machine_id", default="-")


class MachineIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.machine_id = machine_id_var.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(machine_id)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
for _handler in logging.root.handlers:
    _handler.addFilter(MachineIdFilter())
logging.getLogger("driver").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


class Config(BaseSettings):
    machine_id: str = "test-1"
    nats_servers: str = "nats://localhost:4222"
    fake_command_delay: float = 0.0

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a software-only PUDA test edge",
    )
    parser.add_argument(
        "--id",
        "--machine-id",
        dest="machine_id",
        help="Machine ID (overrides MACHINE_ID)",
    )
    return parser.parse_args(argv)


async def run_edge(machine_id: str, config: Config) -> None:
    """Initialize the driver and NATS client, then run until cancelled."""
    machine_id_var.set(machine_id)
    logger.info("Initializing driver for %s", machine_id)
    driver = Driver(command_delay=config.fake_command_delay)

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_server_list,
        machine_id=machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_position(driver.get_position())
        sensor = None
        if hasattr(psutil, "sensors_temperatures"):
            all_temps = psutil.sensors_temperatures() or {}
            sensor = next(
                (
                    v[0]
                    for k in ("coretemp", "cpu_thermal", "k10temp", "acpitz")
                    if (v := all_temps.get(k))
                ),
                None,
            )
        await edge_nats_client.publish_health(
            {
                "cpu": psutil.cpu_percent(interval=None),
                "mem": psutil.virtual_memory().percent,
                "temp": sensor.current if sensor else None,
            }
        )

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
        state_handler=driver.snapshot,
    )
    await runner.connect()
    logger.info(
        "==================== %s Edge Service Ready. Publishing telemetry... ====================",
        machine_id,
    )
    await runner.run()


async def _supervised(machine_id: str, config: Config) -> None:
    machine_id_var.set(machine_id)
    while True:
        try:
            await run_edge(machine_id, config)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fatal error in %s, retrying in 5s", machine_id)
            await asyncio.sleep(5)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = load_config()
    machine_id = args.machine_id or config.machine_id
    try:
        asyncio.run(_supervised(machine_id, config))
    except KeyboardInterrupt:
        logger.warning("Gracefully stopping...")
        sys.exit(0)


if __name__ == "__main__":
    main()
