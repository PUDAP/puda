"""
Main entry point for the Balance edge service.

This module provides the main event loop for the mass balance, handling command
execution via NATS messaging, telemetry publishing, and connection management.
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

from balance_driver.machines import Balance
from balance_driver.core.logging import setup_logging

# Configure logging
setup_logging(log_level=logging.INFO)
logging.getLogger("balance_driver").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class Config(BaseSettings):
    machine_id: str
    nats_servers: str
    balance_port: str
    baudrate: int = 115200
    mode: str = "arduino"
    bridge_host: str = "localhost"
    bridge_port: int = 9000

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


# ---------------------------------------------------------------------------
# Balance command adapter
#
# EdgeRunner dispatches by calling driver.execute_command(name, params).
# Each cmd_* method maps one NATS command name to a Balance driver call.
# ---------------------------------------------------------------------------

class BalanceEdgeDriver:
    """Adapter that maps NATS command names to Balance driver calls."""

    def __init__(self, balance: Balance) -> None:
        self._balance = balance

    def execute_command(self, name: str, params: dict) -> dict:
        handler = getattr(self, f"cmd_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown command: {name!r}")
        return handler(params)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def cmd_get_mass(self, params: dict) -> dict:
        """Get the current mass reading in grams.

        Params:
            retries (int, optional):     Max read attempts (default: 3).
            retry_delay (float, optional): Seconds between retries (default: 1.0).
        """
        mass = self._balance.get_mass(
            retries=params.get("retries", 3),
            retry_delay=params.get("retry_delay", 1.0),
        )
        return {"mass_g": mass, "port": self._balance.port}

    def cmd_get_latest(self, params: dict) -> dict:
        """Get the full latest reading dict (non-blocking)."""
        return self._balance.get_latest()

    def cmd_read(self, params: dict) -> dict:
        """Trigger a read from the balance.

        Params:
            num_readings (int, optional):  Readings to average (default: 1).
            wait_time (float, optional):   Seconds per reading (default: 0.5).
        """
        return self._balance.read(
            num_readings=params.get("num_readings", 1),
            wait_time=params.get("wait_time", 0.5),
        )

    # ------------------------------------------------------------------
    # Tare
    # ------------------------------------------------------------------

    def cmd_tare(self, params: dict) -> dict:
        """Tare (zero) the balance.

        Params:
            wait (float, optional):          Stabilisation wait in seconds (default: 5.0).
            tare_command (str, optional):    Serial tare command character (default: "t").
        """
        ok = self._balance.tare(
            wait=params.get("wait", 5.0),
            tare_command=params.get("tare_command", "t"),
        )
        return {"tared": ok, "port": self._balance.port}

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def cmd_connect(self, params: dict) -> dict:
        """Connect to the balance via the bridge."""
        return self._balance.connect()

    def cmd_disconnect(self, params: dict) -> dict:
        """Disconnect from the balance."""
        return self._balance.disconnect()

    def cmd_is_connected(self, params: dict) -> dict:
        return {"connected": self._balance.is_connected(), "port": self._balance.port}

    # ------------------------------------------------------------------
    # Status & diagnostics
    # ------------------------------------------------------------------

    def cmd_status(self, params: dict) -> dict:
        """Get connection and reader status."""
        return self._balance.status()

    def cmd_monitor(self, params: dict) -> dict:
        """Capture raw serial data for debugging.

        Params:
            duration (int, optional): Monitoring duration in seconds (default: 10).
        """
        return self._balance.monitor(duration=params.get("duration", 10))

    def cmd_diagnose(self, params: dict) -> dict:
        """Test multiple baud rates to find the correct one."""
        return self._balance.diagnose()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def cmd_set_calibration(self, params: dict) -> dict:
        """Set ADC-to-grams calibration parameters.

        Params:
            slope (float):              ADC counts per gram.
            intercept (float, optional): ADC offset at zero grams (default: 0.0).
        """
        return self._balance.set_calibration(
            slope=params["slope"],
            intercept=params.get("intercept", 0.0),
        )

    def cmd_get_calibration(self, params: dict) -> dict:
        """Get the current calibration."""
        return self._balance.get_calibration()

    def cmd_load_default_calibration(self, params: dict) -> dict:
        """Load the built-in 100 g load-cell calibration."""
        return self._balance.load_default_calibration()

    def cmd_load_calibration_from_csv(self, params: dict) -> dict:
        """Load calibration from a CSV string.

        Params:
            csv_data (str): CSV content (header + data rows).
        """
        return self._balance.load_calibration_from_csv(params["csv_data"])

    def cmd_enable_calibration(self, params: dict) -> dict:
        """Enable or disable ADC-to-grams conversion.

        Params:
            enabled (bool): True to enable, False to disable.
        """
        return self._balance.enable_calibration(params.get("enabled", True))

    # ------------------------------------------------------------------
    # Telemetry helper
    # ------------------------------------------------------------------

    def get_health(self) -> dict:
        try:
            status = self._balance.status()
            return {
                "connected": status.get("connected", False),
                "mass_g": status.get("latest_mass_g"),
                "port": self._balance.port,
                "mode": self._balance.mode,
            }
        except Exception:
            return {"connected": False, "port": self._balance.port}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    """Initialize the Balance driver and NATS client, then run the edge runner."""
    config = load_config()
    logger.info("Config loaded for %s", config.machine_id)
    logger.info("Full config: %s", config.model_dump())

    logger.info("Initializing Balance driver")
    balance = Balance(
        port=config.balance_port,
        baudrate=config.baudrate,
        mode=config.mode,
        bridge_host=config.bridge_host,
        bridge_port=config.bridge_port,
    )
    balance.connect()
    logger.info("Balance initialized successfully on %s", config.balance_port)

    driver = BalanceEdgeDriver(balance)

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_server_list,
        machine_id=config.machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        # Run synchronous get_mass in a thread to avoid blocking the event loop
        mass = await asyncio.to_thread(balance.get_mass, 1, 0.1)
        await edge_nats_client.publish_health({
            "connected": balance.is_connected(),
            "mass_g": mass,
            "port": config.balance_port,
        })

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
        state_handler=lambda: driver.get_health(),
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
