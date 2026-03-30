"""HTTP client for the Balance Bridge service.

The Balance Bridge runs on the Windows host and exposes a REST API on
port 9000.  This module centralises all HTTP communication so higher-level
controllers never deal with raw URLs or timeouts directly.

Example::

    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient()
    if client.is_connected():
        resp = client.get("/")
        print(resp.json())
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_HOST = "localhost"
DEFAULT_BRIDGE_PORT = 9000
_CONNECT_TIMEOUT = 5  # seconds for reachability checks


class BalanceBridgeClient:
    """Thin wrapper around :mod:`requests` pre-configured for the Balance Bridge API.

    Args:
        host: Hostname or IP address of the Balance Bridge service.
            Defaults to ``"localhost"``.
        port: HTTP port the bridge listens on.  Defaults to ``9000``.
        timeout: Default request timeout in seconds.  Defaults to ``10``.

    Attributes:
        base_url: Computed base URL, e.g. ``"http://localhost:9000"``.
    """

    def __init__(
        self,
        host: str = DEFAULT_BRIDGE_HOST,
        port: int = DEFAULT_BRIDGE_PORT,
        timeout: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` if the Balance Bridge is reachable via ``GET /``."""
        try:
            resp = requests.get(
                f"{self.base_url}/",
                timeout=_CONNECT_TIMEOUT,
            )
            reachable = resp.status_code == 200
            if reachable:
                logger.debug("Balance Bridge at %s is reachable.", self.base_url)
            else:
                logger.warning(
                    "Balance Bridge health check returned HTTP %s.", resp.status_code
                )
            return reachable
        except requests.exceptions.ConnectionError:
            logger.warning(
                "Cannot reach Balance Bridge at %s (connection refused).",
                self.base_url,
            )
            return False
        except requests.exceptions.Timeout:
            logger.warning(
                "Balance Bridge health check timed out at %s.", self.base_url
            )
            return False

    # ------------------------------------------------------------------
    # HTTP verbs
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        """Perform a GET request against *path* on the bridge API.

        Args:
            path: URL path, e.g. ``"/balance/status"``.
            **kwargs: Forwarded to :func:`requests.get`.

        Returns:
            The :class:`requests.Response` object.
        """
        kwargs.setdefault("timeout", self.timeout)
        url = f"{self.base_url}{path}"
        logger.debug("GET %s", url)
        return requests.get(url, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        """Perform a POST request against *path* on the bridge API.

        Args:
            path: URL path, e.g. ``"/balance/connect"``.
            **kwargs: Forwarded to :func:`requests.post`.

        Returns:
            The :class:`requests.Response` object.
        """
        kwargs.setdefault("timeout", self.timeout)
        url = f"{self.base_url}{path}"
        logger.debug("POST %s", url)
        return requests.post(url, **kwargs)
