#!/usr/bin/env python3
"""
Opentrons Edge Device
Real Opentrons OT-2 robot interface via NATS.io communication
Executes protocols received via NATS and reports results back
"""

import asyncio
import logging
import argparse
from opentrons_device import OpentronsEdgeDevice

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Opentrons Edge Device - Real Opentrons OT-2 robot interface via NATS"
    )
    parser.add_argument(
        "--nats-servers",
        nargs="+",
        default=["nats://localhost:4222"],
        help="NATS server URLs (default: nats://localhost:4222)",
    )
    parser.add_argument(
        "--robot-ip",
        default="192.168.50.64",
        help="Opentrons robot IP address (default: 192.168.50.64)",
    )
    parser.add_argument(
        "--robot-port",
        type=int,
        default=31950,
        help="Opentrons robot API port (default: 31950)",
    )

    args = parser.parse_args()

    print("Starting Opentrons Edge Device")
    print(f"NATS Servers: {args.nats_servers}")
    print(f"Opentrons Robot: {args.robot_ip}:{args.robot_port}")

    edge_device = OpentronsEdgeDevice(
        robot_ip=args.robot_ip,
        robot_port=args.robot_port,
        nats_servers=args.nats_servers,
    )

    # Run the async event loop
    asyncio.run(edge_device.run())


if __name__ == "__main__":
    main()
