"""
Main entry point for the test-edge machine service.

Software-only simulator for local PUDA testing. One process can run a single
machine or a fleet of instances, each with its own MACHINE_ID on NATS.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import logging
import os
import sys
from pathlib import Path

import psutil
from pydantic_settings import BaseSettings, SettingsConfigDict
from puda import EdgeNatsClient, EdgeRunner

from driver import Driver
from ids import resolve_machine_ids

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
    machine_id: str | None = None
    machine_prefix: str = "test"
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
        description="Run one or more software-only PUDA test edges",
    )
    parser.add_argument(
        "--id",
        "--machine-id",
        dest="machine_id",
        help="Single machine ID (overrides MACHINE_ID)",
    )
    parser.add_argument(
        "--ids",
        help="Comma-separated machine IDs, e.g. alpha,beta,gamma",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Start N instances named {prefix}-1 .. {prefix}-N",
    )
    parser.add_argument(
        "--prefix",
        help="Prefix used with --count (default: test, or MACHINE_PREFIX)",
    )
    return parser.parse_args(argv)


def instance_ids(args: argparse.Namespace, config: Config) -> list[str]:
    count = args.count
    if count is None:
        count_env = os.getenv("COUNT", "").strip()
        count = int(count_env) if count_env else None
    return resolve_machine_ids(
        ids=args.ids or os.getenv("MACHINE_IDS"),
        count=count,
        prefix=args.prefix or config.machine_prefix,
        machine_id=args.machine_id or config.machine_id,
    )


async def run_edge(machine_id: str, config: Config) -> None:
    """Initialize one driver and NATS client, then run until cancelled."""
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


async def run_fleet(machine_ids: list[str], config: Config) -> None:
    logger.info("Starting %d edge instance(s): %s", len(machine_ids), ", ".join(machine_ids))
    tasks = [asyncio.create_task(_supervised(mid, config), name=mid) for mid in machine_ids]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = load_config()
    ids = instance_ids(args, config)
    if not ids:
        logger.error("No machine IDs to start")
        sys.exit(1)
    try:
        asyncio.run(run_fleet(ids, config))
    except KeyboardInterrupt:
        logger.warning("Gracefully stopping...")
        sys.exit(0)


if __name__ == "__main__":
    main()
