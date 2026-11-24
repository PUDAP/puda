"""Edge process used by the integration tests.

    python edge_driver.py <nats_url> <machine_id> <full|minimal>

``full`` implements every lifecycle method; ``minimal`` has a single command so
tests can check behaviour when the driver lacks pause/resume/reset/estop.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time

from puda import EdgeNatsClient, EdgeRunner, command

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class FullDriver:
    """Integration-test machine with every lifecycle method."""

    def __init__(self) -> None:
        self._stop = threading.Event()

    @command
    def echo(self, message: str = "") -> dict:
        """Return the message."""
        print(f"EXEC echo {message}", flush=True)
        return {"message": message}

    @command
    def hold(self, seconds: float = 1.0) -> dict:
        """Block for ``seconds`` unless stopped."""
        print(f"EXEC hold {seconds}", flush=True)
        self._stop.clear()
        stopped = self._stop.wait(seconds)
        print(f"DONE hold stopped={stopped}", flush=True)
        return {"waited": seconds, "stopped": stopped}

    @command
    def fail(self, message: str = "boom") -> None:
        """Always raise."""
        raise RuntimeError(message)

    @command
    def pause(self) -> dict:
        """Driver pause hook."""
        return {"paused": True}

    @command
    def resume(self) -> dict:
        """Driver resume hook."""
        return {"paused": False}

    @command
    def reset(self) -> dict:
        """Driver reset hook."""
        return {"reset": True}

    @command
    def estop(self) -> dict:
        """Hardware stop."""
        self._stop.set()
        return {"stopped": True}

    @command
    def abort(self) -> dict:
        """Soft stop of the running command."""
        print("EXEC abort", flush=True)
        self._stop.set()
        return {"aborted": True}


class MinimalDriver:
    """Integration-test machine with no lifecycle hooks (echo and an unstoppable hold)."""

    @command
    def echo(self, message: str = "") -> dict:
        """Return the message."""
        return {"message": message}

    @command
    def hold(self, seconds: float = 1.0) -> dict:
        """Block for ``seconds``; cannot be stopped."""
        time.sleep(seconds)
        return {"waited": seconds}


async def main(url: str, machine_id: str, kind: str) -> None:
    driver = FullDriver() if kind == "full" else MinimalDriver()
    client = EdgeNatsClient(servers=[url], machine_id=machine_id)
    runner = EdgeRunner(nats_client=client, machine_driver=driver, host_health=False)
    await runner.connect()
    await runner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main(*sys.argv[1:4]))
    except KeyboardInterrupt:
        pass
