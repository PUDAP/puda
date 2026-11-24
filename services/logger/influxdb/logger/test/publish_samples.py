"""Publish raw SDK-shaped samples to a test broker in plaintext or E2EE mode."""

import asyncio
import json
import sys
from pathlib import Path

import nats
from puda import e2e

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subscriber import Config, Subscriber  # noqa: E402


async def main():
    config = Config.from_env()
    nc = await nats.connect(servers=config.servers, **config.connect_options)
    try:
        subscriber = Subscriber(config)
        subscriber.js = nc.jetstream()
        await subscriber.sync_keyring()
        data = {
            "header": {
                "machine_id": "logger-test",
                "timestamp": "2026-07-07T09:41:42Z",
                "username": "test",
                "user_id": "test-user",
                "run_id": "test-run",
            },
            "command": {"name": "sample", "step_number": 1, "version": "1.0"},
            "response": {"status": "success", "completed_at": "2026-07-07T09:41:43Z"},
        }
        for suffix in (
            "cmd.queue",
            "cmd.immediate",
            "cmd.response.queue",
            "cmd.response.immediate",
            "tlm.health",
        ):
            subject = "puda.logger-test." + suffix
            payload = (
                {"timestamp": "2026-07-07T09:41:42Z", "cpu": 6.0}
                if suffix == "tlm.health"
                else data
            )
            await nc.publish(subject, e2e.seal(subject, json.dumps(payload).encode()))
        await nc.flush()
    finally:
        await nc.close()
    print("Published five sample messages for logger-test")


if __name__ == "__main__":
    asyncio.run(main())
