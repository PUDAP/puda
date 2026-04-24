"""
Send an update command to a PUDA edge over NATS.

Publishes a NATSMessage to ``puda.<machine_id>.update`` (core NATS, no JetStream)
with ``command.name="update"`` and ``command.params`` describing the source
(git or docker). Subscribes to ``puda.<machine_id>.update.response`` before
publishing so the response from the edge is captured.

Usage
-----
Default (edge fetches from its existing origin and resets to main):

    python libs/puda-python/tests/send_update.py --machine-id update-test

Git update, explicit params (``--ref`` is optional; when set the edge
re-points ``origin`` to it before fetching):

    python libs/puda-python/tests/send_update.py \\
        --machine-id update-test \\
        --source-type git \\
        --ref https://github.com/PUDAP/machine-template.git \\
        --checkout main

Docker update:

    python libs/puda-python/tests/send_update.py \\
        --machine-id update-test \\
        --source-type docker \\
        --ref ghcr.io/pudap/machine-template:latest

NATS servers default to the hardcoded tailnet addresses in this script; use
``--servers`` to override.

Note: the edge exits after a successful update so no second "restart done"
response is published -- the ``update.response`` message IS the confirmation
that the pull worked; the process then disconnects and the supervisor brings
it back up.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
import nats
from nats.aio.msg import Msg

from puda.models import (
    CommandRequest,
    MessageHeader,
    MessageType,
    NATSMessage,
)

DEFAULT_NATS_SERVERS = (
    "nats://100.109.131.12:4222,"
    "nats://100.109.131.12:4223,"
    "nats://100.109.131.12:4224"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("send_update")


def get_nats_servers() -> list[str]:
    return [s.strip() for s in DEFAULT_NATS_SERVERS.split(",") if s.strip()]


def build_message(
    machine_id: str,
    source_type: str,
    ref: str,
    checkout: str | None,
    user_id: str,
    username: str,
) -> NATSMessage:
    params: dict[str, str] = {"source_type": source_type, "ref": ref}
    if checkout:
        params["checkout"] = checkout
    
    return NATSMessage(
        header=MessageHeader(
            message_type=MessageType.COMMAND,
            user_id=user_id,
            username=username,
            machine_id=machine_id,
            run_id=str(uuid.uuid4()),
        ),
        command=CommandRequest(
            name="update",
            machine_id=machine_id,
            params=params,
            step_number=0,
        ),
    )


async def wait_for_alive(nc: nats.NATS, machine_id: str, timeout: float) -> bool:
    """
    Block until a heartbeat from ``puda.<machine_id>.tlm.heartbeat`` arrives.
    
    Returns True if at least one heartbeat was observed within ``timeout``
    seconds, False otherwise. Edges publish this subject roughly once per
    second from their telemetry loop, so a 5s timeout is plenty in practice.
    """
    subject = f"puda.{machine_id.replace('.', '-')}.tlm.heartbeat"
    seen = asyncio.Event()
    
    async def _on_hb(_msg: Msg) -> None:
        seen.set()
    
    logger.info("Waiting up to %ss for heartbeat on %s ...", timeout, subject)
    sub = await nc.subscribe(subject, cb=_on_hb)
    try:
        try:
            await asyncio.wait_for(seen.wait(), timeout=timeout)
            logger.info("Heartbeat received; machine %s is alive", machine_id)
            return True
        except asyncio.TimeoutError:
            logger.error(
                "No heartbeat from %s within %ss -- is the edge process running?",
                machine_id, timeout,
            )
            return False
    finally:
        try:
            await sub.unsubscribe()
        except Exception:
            pass


async def send_update(
    machine_id: str,
    source_type: str,
    ref: str,
    checkout: str | None,
    timeout: float,
    servers: list[str],
    alive_timeout: float = 5.0,
) -> int:
    response_subject = f"puda.{machine_id.replace('.', '-')}.update.response"
    update_subject = f"puda.{machine_id.replace('.', '-')}.update"
    
    message = build_message(
        machine_id=machine_id,
        source_type=source_type,
        ref=ref,
        checkout=checkout,
        user_id=str(uuid.uuid4()),
        username="update-test-script",
    )
    
    response_received = asyncio.Event()
    captured: dict[str, NATSMessage | None] = {"reply": None}
    
    async def on_response(msg: Msg) -> None:
        try:
            reply = NATSMessage.model_validate_json(msg.data)
        except Exception as e:
            logger.error("Could not parse response: %s", e)
            return
        if reply.header.run_id != message.header.run_id:
            logger.debug("Ignoring response for a different run_id: %s", reply.header.run_id)
            return
        captured["reply"] = reply
        response_received.set()
    
    logger.info("Connecting to NATS: %s", servers)
    nc = await nats.connect(servers=servers, connect_timeout=5)
    try:
        if not await wait_for_alive(nc, machine_id, alive_timeout):
            return 3
        
        sub = await nc.subscribe(response_subject, cb=on_response)
        logger.info("Subscribed to %s", response_subject)
        
        logger.info(
            "Publishing update to %s (source_type=%s, ref=%s)",
            update_subject, source_type, ref,
        )
        await nc.publish(update_subject, message.model_dump_json().encode())
        await nc.flush()
        
        logger.info("Waiting up to %ss for update response...", timeout)
        try:
            await asyncio.wait_for(response_received.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Timed out waiting for update response")
            return 2
        finally:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        
        reply = captured["reply"]
        if reply is None or reply.response is None:
            logger.error("Malformed response: %s", reply)
            return 2
        
        status = reply.response.status.value
        code = reply.response.code.value if reply.response.code else None
        logger.info(
            "Update response: status=%s code=%s message=%s data=%s",
            status, code, reply.response.message, reply.response.data,
        )
        print(json.dumps(
            {
                "status": status,
                "code": code,
                "message": reply.response.message,
                "data": reply.response.data,
                "run_id": reply.header.run_id,
            },
            indent=2,
        ))
        return 0 if status == "success" else 1
    finally:
        await nc.drain()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send an update command to a PUDA edge over NATS.",
    )
    parser.add_argument(
        "--machine-id", default="update-test",
        help="Target machine_id (default: update-test, matching tests/machine-template/edge/.env)",
    )
    parser.add_argument(
        "--source-type", choices=["git", "docker"], default="git",
        help="Update source type (default: git)",
    )
    parser.add_argument(
        "--ref", default=None,
        help=(
            "For git: optional repo URL; when set, the edge re-points "
            "'origin' to it before fetching. For docker: required image:tag."
        ),
    )
    parser.add_argument(
        "--checkout", default="main",
        help="Git branch, tag, or commit SHA to reset to (git only, default: main)",
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0,
        help="Seconds to wait for the edge's update response (default: 60)",
    )
    parser.add_argument(
        "--alive-timeout", type=float, default=5.0,
        help=(
            "Seconds to wait for a heartbeat on puda.<machine_id>.tlm.heartbeat "
            "before publishing the update (default: 5). Fails fast with exit "
            "code 3 if no heartbeat arrives."
        ),
    )
    parser.add_argument(
        "--servers", default=None,
        help="Comma-separated NATS URLs (default: tailnet servers in this script).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source_type == "docker" and not args.ref:
        logger.error("--ref is required for docker updates")
        return 2
    servers = (
        [s.strip() for s in args.servers.split(",") if s.strip()]
        if args.servers
        else get_nats_servers()
    )
    if args.source_type == "docker" and args.checkout == "main":
        args.checkout = None  # meaningless for docker; don't send it
    return asyncio.run(send_update(
        machine_id=args.machine_id,
        source_type=args.source_type,
        ref=args.ref,
        checkout=args.checkout,
        timeout=args.timeout,
        servers=servers,
        alive_timeout=args.alive_timeout,
    ))


if __name__ == "__main__":
    sys.exit(main())
