"""HTTP client for the Opentrons OT-2 REST API.

The OT-2 exposes a REST API on port 31950.  Every request needs the
``opentrons-version`` header; this module centralises that so individual
controllers never have to repeat it.

Example::

    from opentrons_driver.core.http_client import OT2HttpClient

    client = OT2HttpClient("192.168.50.64")
    if client.is_connected():
        resp = client.get("/health")
        print(resp.json())
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_ROBOT_IP = "192.168.50.64"
DEFAULT_PORT = 31950
_CONNECT_TIMEOUT = 5  # seconds for connection checks


class OT2HttpClient:
    """Thin wrapper around :mod:`requests` pre-configured for the OT-2 API.

    Args:
        robot_ip: IP address of the OT-2 robot on the local network.
        port: HTTP port the robot listens on (default ``31950``).
        timeout: Default request timeout in seconds (default ``10``).
    """

    def __init__(
        self,
        robot_ip: str = DEFAULT_ROBOT_IP,
        port: int = DEFAULT_PORT,
        timeout: int = 10,
    ) -> None:
        self.robot_ip = robot_ip
        self.port = port
        self.base_url = f"http://{robot_ip}:{port}"
        self.headers = {"opentrons-version": "*"}
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if the robot is reachable and responds to ``GET /health``."""
        try:
            resp = requests.get(
                f"{self.base_url}/health",
                headers=self.headers,
                timeout=_CONNECT_TIMEOUT,
            )
            connected = resp.status_code == 200
            if connected:
                logger.debug("OT-2 at %s is reachable.", self.base_url)
            else:
                logger.warning(
                    "OT-2 health check returned HTTP %s.", resp.status_code
                )
            return connected
        except requests.exceptions.ConnectionError:
            logger.warning("Cannot reach OT-2 at %s (connection refused).", self.base_url)
            return False
        except requests.exceptions.Timeout:
            logger.warning("OT-2 health check timed out at %s.", self.base_url)
            return False

    # ------------------------------------------------------------------
    # HTTP verbs
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        """Perform a GET request against *path* on the robot API.

        Args:
            path: URL path, e.g. ``"/runs"``.
            **kwargs: Forwarded to :func:`requests.get`.

        Returns:
            The :class:`requests.Response` object.
        """
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("headers", self.headers)
        url = f"{self.base_url}{path}"
        logger.debug("GET %s", url)
        return requests.get(url, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        """Perform a POST request against *path* on the robot API.

        Args:
            path: URL path, e.g. ``"/protocols"``.
            **kwargs: Forwarded to :func:`requests.post`.

        Returns:
            The :class:`requests.Response` object.
        """
        kwargs.setdefault("timeout", self.timeout)
        # Merge caller-supplied headers on top of the required opentrons header
        caller_headers = kwargs.pop("headers", {})
        merged = {**self.headers, **caller_headers}
        url = f"{self.base_url}{path}"
        logger.debug("POST %s", url)
        return requests.post(url, headers=merged, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        """Perform a DELETE request against *path* on the robot API."""
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("headers", self.headers)
        url = f"{self.base_url}{path}"
        logger.debug("DELETE %s", url)
        return requests.delete(url, **kwargs)
