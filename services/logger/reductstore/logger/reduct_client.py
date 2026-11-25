"""ReductStore client for PUDA NATS logs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from reduct import Client, ReductError

logger = logging.getLogger(__name__)

ENTRY_COMMANDS = "commands"
ENTRY_TELEMETRY = "telemetry"


def to_microseconds(timestamp: datetime) -> int:
    """Convert a timezone-aware datetime to Unix microseconds."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return int(timestamp.timestamp() * 1_000_000)


class ReductClient:
    """Thin wrapper around reduct-py for writing labeled JSON records."""

    def __init__(self, url: str, token: str, bucket: str):
        self.url = url
        self.token = token
        self.bucket_name = bucket
        self._client: Optional[Client] = None
        self._bucket = None
        self._last_ts: dict[str, int] = {
            ENTRY_COMMANDS: 0,
            ENTRY_TELEMETRY: 0,
        }
        self._locks: dict[str, asyncio.Lock] = {
            ENTRY_COMMANDS: asyncio.Lock(),
            ENTRY_TELEMETRY: asyncio.Lock(),
        }

    async def connect(self) -> None:
        """Open the HTTP client and ensure the target bucket exists."""
        self._client = Client(self.url, api_token=self.token)
        self._bucket = await self._client.create_bucket(
            self.bucket_name,
            exist_ok=True,
        )
        logger.info(
            "Connected to ReductStore at %s (bucket=%s)",
            self.url,
            self.bucket_name,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._bucket = None
            logger.info("Closed ReductStore connection")

    async def write(
        self,
        entry: str,
        data: bytes,
        timestamp: datetime,
        labels: dict[str, Any],
    ) -> None:
        """Write a JSON record, bumping the timestamp on uniqueness conflicts."""
        if self._bucket is None:
            raise RuntimeError("ReductStore client is not connected")

        string_labels = {
            key: str(value)
            for key, value in labels.items()
            if value is not None and value != ""
        }
        ts = to_microseconds(timestamp)
        lock = self._locks.setdefault(entry, asyncio.Lock())

        async with lock:
            last = self._last_ts.get(entry, 0)
            if ts <= last:
                ts = last + 1

            for _ in range(100):
                try:
                    await self._bucket.write(
                        entry,
                        data,
                        timestamp=ts,
                        labels=string_labels,
                        content_type="application/json",
                    )
                    self._last_ts[entry] = ts
                    return
                except ReductError as exc:
                    if exc.status_code != 409:
                        raise
                    ts += 1

            raise RuntimeError(
                f"Could not find a unique timestamp for entry '{entry}'"
            )
