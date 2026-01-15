"""
Generic Serial Controller for communicating with devices over serial ports.
"""

import time
import logging
import threading
from typing import Optional, List, Tuple
from abc import ABC, abstractmethod
import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)


def list_serial_ports(filter_desc: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """
    Lists available serial ports on the system.

    This is a utility function that can be used independently of any controller instance.
    It's useful for discovering available serial ports before initializing a controller.

    Args:
        filter_desc: Optional string to filter ports by description (case-insensitive).
                     If provided, only ports whose description contains this string will be returned.

    Returns:
        List of tuples, where each tuple contains (port_name, description, hwid).
    """
    all_ports = serial.tools.list_ports.comports()
    filtered_ports = []
    for port in all_ports:
        if filter_desc and filter_desc.lower() not in port.description.lower():
            continue
        filtered_ports.append((port.device, port.description, port.hwid))
    return filtered_ports


class SerialController(ABC):
    """
    Abstract base class for serial controllers.
    """
    DEFAULT_BAUDRATE = 9600
    DEFAULT_TIMEOUT = 30  # seconds
    POLL_INTERVAL = 0.1  # seconds

    def __init__(self, port_name, baudrate=DEFAULT_BAUDRATE, timeout=DEFAULT_TIMEOUT):
        self._serial = None
        self.port_name = port_name
        self.baudrate = baudrate
        self._timeout = timeout
        self._logger = logger
        
        # lock to prevent concurrent access to the serial port
        self._lock = threading.Lock()

    def connect(self) -> None:
        """
        Establishes the serial connection to the port.
        """
        if not self.port_name:
            self._logger.error("Port name is not set. Cannot connect.")
            raise IOError("Cannot connect: Serial port name is not set.")

        if self.is_connected:
            self._logger.warning("Already connected. Disconnecting and reconnecting...")
            self.disconnect()

        try:
            self._logger.info(
                "Attempting connection to %s at %s baud.",
                self.port_name,
                self.baudrate,
            )
            self._serial = serial.Serial(
                port=self.port_name,
                baudrate=self.baudrate,
                timeout=self._timeout,
            )
            self._serial.flush()
            self._logger.info("Successfully connected to %s.", self.port_name)
        except serial.SerialException as e:
            self._serial = None
            self._logger.error("Error connecting to port %s: %s", self.port_name, e)
            raise serial.SerialException(
                f"Error connecting to port {self.port_name}: {e}"
            )

    def disconnect(self) -> None:
        """
        Closes the serial connection.
        """
        if self._serial and self._serial.is_open:
            port_name = self._serial.port
            self._serial.close()
            self._serial = None
            self._logger.info("Serial connection to %s closed.", port_name)
        else:
            self._logger.warning(
                "Serial port already disconnected or was never connected."
            )

    @property
    def is_connected(self) -> bool:
        """Checks if the serial port is currently open."""
        return self._serial is not None and self._serial.is_open

    def _send_command(self, command: str) -> None:
        """
        Sends a command to the device.
        Note: This method should be called while holding self._lock to ensure
        atomic command/response pairing.
        """
        self._logger.info("-> Sending: %r", command)

        if not self.is_connected or not self._serial:
            self._logger.error(
                "Attempt to send command '%s' failed: Device not connected.",
                command,
            )
            # Retain raising an error for being disconnected, as that's a connection state issue
            raise serial.SerialException("Device disconnected. Call connect() first.")

        try:
            self._serial.reset_input_buffer()  # clear input buffer
            self._serial.reset_output_buffer()  # clear output buffer
            self._serial.flush()
            self._serial.write(bytes(command, "utf-8"))

        except serial.SerialTimeoutException as e:
            # Log the timeout error and return None as requested (no re-raise)
            self._logger.error("Timeout on command '%s'. Error: %s", command, e)
            return None

        except serial.SerialException as e:
            self._logger.error(
                "Serial error writing command '%s'. Error: %s",
                command,
                e,
            )
            return None

    def _read_response(self, timeout: int = None) -> str:
        """
        Generic, blocking read that respects timeout and returns
        all data that arrived within the timeout period.
        """
        if not self.is_connected or not self._serial:
            raise serial.SerialException("Device not connected.")

        if timeout is None:
            timeout = self._timeout

        start_time = time.time()
        response = b""

        while time.time() - start_time < timeout:
            if self._serial.in_waiting > 0:
                # Read all available bytes
                response += self._serial.read(self._serial.in_waiting)

                # Check for expected response markers for early return for qubot
                if b"ok" in response or b"err" in response:
                    break
                
                # for sartorius since res not returning ok or err
                if b"\xba\r" in response:
                    break
            else:
                time.sleep(0.1)

        # Timeout reached - check what we got
        if not response:
            self._logger.error("No response within %s seconds.", timeout)
            raise serial.SerialTimeoutException(
                f"No response received within {timeout} seconds."
            )

        decoded_response = response.decode("utf-8", errors="ignore").strip()
        if "ok" in decoded_response.lower():
            self._logger.debug("<- Received response: %r", decoded_response)
        elif "err" in decoded_response.lower():
            self._logger.error("<- Received error: %r", decoded_response)
        elif "º" in decoded_response: # for sartorius (since res not returning ok or err)
            self._logger.debug("<- Received response: %r", decoded_response)
        else:
            self._logger.warning(
                "<- Received unexpected response (no 'ok' or 'err'): %r", decoded_response
            )
        
        return decoded_response
    
    @abstractmethod
    def _build_command(self, command: str, value: Optional[str] = None) -> str:
        """
        Build a command string according to the device protocol.
        
        There might be special starting and ending characters for devices
        """
        raise NotImplementedError

    def execute(self, command: str, value: Optional[str] = None, timeout: int = None) -> str:
        """
        Send a command and read the response atomically.
        
        This method combines sending a command and reading its response into a
        single atomic operation, ensuring the response corresponds to the command
        that was just sent. The entire operation is protected by a lock to prevent
        concurrent commands from interfering with each other.
        
        This is the preferred method for commands that require a response.
        
        Args:
            command: Command string to send (should include protocol terminator if needed)
            value: Optional value parameter for the command
            
        Returns:
            Response string from the device
            
        Raises:
            serial.SerialException: If device is not connected or communication fails
            serial.SerialTimeoutException: If no response is received within timeout
        """
        if timeout is None:
            timeout = self._timeout
        # Hold the lock for the entire send+read operation to ensure atomicity
        # This prevents concurrent commands from mixing up responses
        with self._lock:
            self._send_command(self._build_command(command, value))
            return self._read_response(timeout=timeout)