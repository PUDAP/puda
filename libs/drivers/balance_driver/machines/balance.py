"""High-level Balance machine interface.

The :class:`Balance` class is the primary entry-point for this package.  It
wires together the underlying controllers and exposes a clean, intent-oriented
API.  It supports the context-manager protocol so serial connections are
always closed even when exceptions occur.

Example::

    from balance_driver.machines import Balance
    from balance_driver.core.logging import setup_logging
    import logging
    import time

    setup_logging(enable_file_logging=True, log_level=logging.INFO)

    with Balance(port="COM8", baudrate=115200, mode="arduino") as bal:
        time.sleep(2)   # wait for Arduino reset + first reading

        mass = bal.get_mass(retries=3, retry_delay=1.0)
        if mass is not None:
            print(f"{mass:.6f} g  ({mass * 1000:.4f} mg)")
        else:
            print("No reading received — check cable and baud rate.")
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from balance_driver.controllers import calibration as cal_ctrl
from balance_driver.controllers import reading as read_ctrl
from balance_driver.core.http_client import (
    DEFAULT_BRIDGE_HOST,
    DEFAULT_BRIDGE_PORT,
    BalanceBridgeClient,
)

logger = logging.getLogger(__name__)


class Balance:
    """Mass balance driver.

    Connects to a physical balance through the Balance Bridge HTTP service
    and provides a clean Python API for reading mass, taring, calibration,
    and diagnostics.

    Args:
        port: COM port of the balance, e.g. ``"COM8"``.
        baudrate: Serial baud rate.  Defaults to ``115200``.
        mode: ``"arduino"`` for a continuous background reader (Arduino /
            ESP32 load cells), or ``"commercial"`` for command-response
            balances.  Defaults to ``"arduino"``.
        bridge_host: Hostname or IP of the Balance Bridge service.
            Defaults to ``"localhost"``.
        bridge_port: HTTP port of the Balance Bridge service.
            Defaults to ``9000``.
        timeout: HTTP request timeout in seconds.  Defaults to ``10``.

    Attributes:
        client: The underlying
            :class:`~balance_driver.core.http_client.BalanceBridgeClient`.
        port: COM port in use.
        baudrate: Baud rate in use.
        mode: Connection mode in use.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        mode: str = "arduino",
        bridge_host: str = DEFAULT_BRIDGE_HOST,
        bridge_port: int = DEFAULT_BRIDGE_PORT,
        timeout: int = 10,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.mode = mode
        self.client = BalanceBridgeClient(
            host=bridge_host, port=bridge_port, timeout=timeout
        )
        self._connected = False
        logger.info(
            "Balance driver initialised (port=%s baudrate=%s mode=%s bridge=%s:%s)",
            port,
            baudrate,
            mode,
            bridge_host,
            bridge_port,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Balance":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> dict:
        """Connect to the balance via the bridge.

        Returns:
            Connection result dict from the bridge.

        Raises:
            RuntimeError: If the Balance Bridge is unreachable or the serial
                connection fails.
        """
        if not self.client.is_connected():
            raise RuntimeError(
                f"Balance Bridge is not reachable at {self.client.base_url}. "
                "Make sure balance_bridge.py is running: python balance_bridge.py"
            )
        result = read_ctrl.connect_balance(
            self.client,
            port=self.port,
            baudrate=self.baudrate,
            mode=self.mode,
        )
        self._connected = True
        return result

    def disconnect(self) -> dict:
        """Disconnect from the balance.

        Safe to call even if already disconnected.

        Returns:
            Disconnection result dict from the bridge.
        """
        if not self._connected:
            logger.debug("Balance on %s already disconnected — skipping.", self.port)
            return {"status": "not_connected", "port": self.port}
        result = read_ctrl.disconnect_balance(self.client, self.port)
        self._connected = False
        return result

    def is_connected(self) -> bool:
        """Return ``True`` if the balance port is currently connected."""
        try:
            status = read_ctrl.get_balance_status(self.client, self.port)
            return status.get("connected", False)
        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_mass(
        self,
        retries: int = 3,
        retry_delay: float = 1.0,
    ) -> Optional[float]:
        """Get the current mass reading in grams.

        Fetches the latest cached value from the bridge.  If no fresh reading
        is available, retries up to *retries* times with *retry_delay* seconds
        between each attempt.

        Args:
            retries: Maximum number of attempts.  Defaults to ``3``.
            retry_delay: Seconds to wait between retries.  Defaults to ``1.0``.

        Returns:
            Mass in grams, or ``None`` if no reading was received.
        """
        for attempt in range(retries):
            try:
                data = read_ctrl.get_latest_reading(self.client, self.port)
                if data.get("status") == "success" and data.get("mass_g") is not None:
                    mass = data["mass_g"]
                    logger.debug(
                        "Mass reading: %.6f g (attempt %d/%d)",
                        mass,
                        attempt + 1,
                        retries,
                    )
                    return mass
            except RuntimeError as exc:
                logger.warning(
                    "Mass read attempt %d/%d failed: %s", attempt + 1, retries, exc
                )

            if attempt < retries - 1:
                logger.debug("Retrying in %.1f s...", retry_delay)
                time.sleep(retry_delay)

        logger.warning("No mass reading received after %d attempt(s).", retries)
        return None

    def get_latest(self) -> dict:
        """Get the full latest reading dict (non-blocking).

        Returns:
            Reading dict with ``mass_g``, ``mass_mg``, ``fresh``,
            ``age_seconds``, ``calibrated``, and ``calibration`` info.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return read_ctrl.get_latest_reading(self.client, self.port)

    def read(
        self,
        num_readings: int = 1,
        wait_time: float = 0.5,
    ) -> dict:
        """Trigger a read from the balance (may block for commercial mode).

        Args:
            num_readings: Number of readings to average (commercial mode).
            wait_time: Seconds to wait per reading (commercial mode).

        Returns:
            Reading dict with ``mass_g`` and ``mass_mg``.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return read_ctrl.read_balance(
            self.client,
            port=self.port,
            num_readings=num_readings,
            wait_time=wait_time,
        )

    # ------------------------------------------------------------------
    # Tare
    # ------------------------------------------------------------------

    def tare(
        self,
        wait: float = 5.0,
        tare_command: str = "t",
    ) -> bool:
        """Tare (zero) the balance.

        Args:
            wait: Seconds to wait for stabilisation after the tare command.
                Defaults to ``5.0``.
            tare_command: Single-character command sent to the Arduino.
                Defaults to ``"t"``.

        Returns:
            ``True`` on success.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        result = read_ctrl.tare_balance(
            self.client,
            port=self.port,
            wait=wait,
            tare_command=tare_command,
        )
        return result.get("status") == "success"

    # ------------------------------------------------------------------
    # Status & diagnostics
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Get detailed connection and reader status.

        Returns:
            Status dict with ``connected``, ``background_reader_active``,
            ``has_data``, ``baudrate``, ``latest_mass_g``, and
            ``data_age_seconds``.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return read_ctrl.get_balance_status(self.client, self.port)

    def monitor(self, duration: int = 10) -> dict:
        """Capture raw serial data for debugging.

        Args:
            duration: Seconds to monitor.  Defaults to ``10``.

        Returns:
            Monitor dict with ``data_received``, ``total_messages``,
            ``readable_messages``, ``diagnosis``, and ``summary``.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return read_ctrl.monitor_balance(
            self.client, port=self.port, duration=duration
        )

    def diagnose(self) -> dict:
        """Test multiple baud rates to find the correct one.

        Returns:
            Diagnosis dict with ``best_baudrate``, ``results``, ``mass_found``,
            and ``summary``.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return read_ctrl.diagnose_balance(self.client, self.port)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def set_calibration(
        self,
        slope: float,
        intercept: float = 0.0,
    ) -> dict:
        """Set ADC-to-grams calibration parameters and enable them.

        Formula: ``grams = (raw_adc - intercept) / slope``

        Args:
            slope: ADC counts per gram.
            intercept: ADC offset at zero grams.  Defaults to ``0.0``.

        Returns:
            Calibration result dict from the bridge.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return cal_ctrl.set_calibration(
            self.client, port=self.port, slope=slope, intercept=intercept
        )

    def get_calibration(self) -> dict:
        """Get the current calibration for this port.

        Returns:
            Calibration dict with ``slope``, ``intercept``, ``enabled``,
            ``source``, and ``formula``.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return cal_ctrl.get_calibration(self.client, self.port)

    def load_default_calibration(self) -> dict:
        """Load the built-in 100 g load-cell calibration and enable it.

        Returns:
            Calibration result dict.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return cal_ctrl.load_default_calibration(self.client, self.port)

    def load_calibration_from_csv(self, csv_data: str) -> dict:
        """Compute and load calibration from a CSV string.

        Args:
            csv_data: CSV content as a string.  Expected columns:
                ``Calibration weight (g)``, ``Mean``, ``Stdev``, ``% Error``.

        Returns:
            Calibration result dict with computed ``slope`` and ``intercept``.

        Raises:
            RuntimeError: If the bridge request fails or CSV is invalid.
        """
        return cal_ctrl.load_calibration_csv(
            self.client, port=self.port, csv_data=csv_data
        )

    def enable_calibration(self, enabled: bool = True) -> dict:
        """Enable or disable ADC-to-grams conversion.

        Args:
            enabled: ``True`` to enable calibration, ``False`` to disable
                and receive raw ADC counts.

        Returns:
            Result dict with ``enabled`` status.

        Raises:
            RuntimeError: If the bridge request fails.
        """
        return cal_ctrl.enable_calibration(self.client, self.port, enabled)
