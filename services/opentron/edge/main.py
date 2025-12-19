#!/usr/bin/env python3
import asyncio
import argparse
import logging
import sys
from typing import Dict, Any

from base_robot import RobotConfig, ProtocolData
from nats_client import NATSClient
from opentrons_robot import OpentronsRobot

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class OpentronsEdgeDevice:
    """
    Opentrons Edge Device
    Combines a Opentrons robot implementation with NATS communication
    """

    def __init__(self, robot: OpentronsRobot, nats_client: NATSClient):
        self.robot = robot
        self.nats = nats_client
        self.running = False

    async def handle_execute_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle protocol execution command"""
        try:
            protocol_id = payload.get("protocol_id")
            protocol_data = payload.get("protocol_data", {})

            logger.info("Executing protocol %s", protocol_id)

            # Update device status
            self.robot.processing = True
            await self.update_status()

            # Create protocol data object
            protocol = ProtocolData(
                protocol_id=protocol_id,
                protocol_code=protocol_data.get("protocol_code"),
                protocol_data=protocol_data,
                timeout_seconds=protocol_data.get("timeout_seconds", 300),
            )

            # Validate protocol
            validation_result = await self.robot.validate_protocol(protocol)
            if not validation_result["valid"]:
                await self.nats.publish_log(
                    {
                        "event": "protocol_validation_failed",
                        "protocol_id": protocol_id,
                        "errors": validation_result["errors"],
                    }
                )
                return {
                    "status": "failed",
                    "protocol_id": protocol_id,
                    "error": "Validation failed",
                    "errors": validation_result["errors"],
                }

            # Execute protocol in background
            # Note: In a production system, you might want to use a task queue
            # For now, we'll execute it in the background
            execution_result = await self.robot.execute_protocol(protocol)

            # Update status after execution
            await self.update_status()

            # Publish log event
            if execution_result.status == "succeeded":
                await self.nats.publish_log(
                    {
                        "event": "protocol_complete",
                        "protocol_id": protocol_id,
                        "run_id": execution_result.run_id,
                        "elapsed_time": execution_result.elapsed_time,
                    }
                )
            else:
                await self.nats.publish_log(
                    {
                        "event": "protocol_failed",
                        "protocol_id": protocol_id,
                        "error": execution_result.error,
                    }
                )

            # Return response
            return {
                "status": execution_result.status,
                "protocol_id": protocol_id,
                "run_id": execution_result.run_id,
                "elapsed_time": execution_result.elapsed_time,
                "error": execution_result.error,
                "results": execution_result.results,
            }

        except Exception as e:
            logger.error("Error handling execute command: %s", e)
            return {
                "status": "error",
                "protocol_id": payload.get("protocol_id"),
                "error": str(e),
            }

    async def handle_cancel_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle protocol cancellation command"""
        try:
            protocol_id = payload.get("protocol_id")
            logger.info("Cancelling protocol %s", protocol_id)

            # Cancel protocol
            success = await self.robot.cancel_protocol(protocol_id)

            # Update device status
            self.robot.processing = False
            await self.update_status()

            # Publish log event
            await self.nats.publish_log(
                {
                    "event": "protocol_cancelled",
                    "protocol_id": protocol_id,
                    "success": success,
                }
            )

            return {
                "status": "cancelled" if success else "cancel_failed",
                "protocol_id": protocol_id,
                "message": f"Protocol {protocol_id} cancelled"
                if success
                else f"Failed to cancel protocol {protocol_id}",
            }

        except Exception as e:
            logger.error("Error handling cancel command: %s", e)
            return {
                "status": "error",
                "protocol_id": payload.get("protocol_id"),
                "error": str(e),
            }

    async def update_status(self):
        """Update robot status in KV store"""
        robot_status = await self.robot.get_robot_status()
        device_info = self.robot.get_device_info()

        status_data = {
            "status": "busy" if self.robot.processing else "online",
            "processing": self.robot.processing,
            "robot_status": robot_status,
            "capabilities": self.robot.get_capabilities(),
            **device_info,
        }

        await self.nats.update_status_kv(status_data)

    async def send_heartbeat(self):
        """Send heartbeat message"""
        robot_status = await self.robot.get_robot_status()
        device_info = self.robot.get_device_info()

        heartbeat_data = {
            "status": "online",
            "processing": self.robot.processing,
            "robot_status": robot_status,
            "capabilities": self.robot.get_capabilities(),
            **device_info,
        }

        await self.nats.publish_heartbeat(heartbeat_data)

    async def run(self):
        """Run the edge device"""
        # Connect to NATS
        if not await self.nats.connect():
            logger.error("Failed to connect to NATS server")
            return False

        # Check robot connection on startup
        # Get connection info from config (supports IP, serial, ROS, etc.)
        conn_info = self.robot.config.connection_config
        conn_str = str(
            conn_info.get(
                "robot_ip",
                conn_info.get("serial_port", conn_info.get("ros_topic", "unknown")),
            )
        )
        logger.info("Checking connection to robot at %s...", conn_str)
        if not await self.robot.check_connection():
            logger.warning("⚠️ Robot at %s is not accessible", conn_str)
            logger.warning(
                "The edge device will continue running but protocol execution will fail"
            )
        else:
            logger.info("✅ Robot at %s is accessible", conn_str)

        # Subscribe to commands
        await self.nats.subscribe_execute(self.handle_execute_command)
        await self.nats.subscribe_cancel(self.handle_cancel_command)

        # Send initial status
        await self.update_status()
        await self.send_heartbeat()

        logger.info("Robot Edge Device %s running...", self.robot.config.device_id)
        logger.info("Waiting for protocol commands...")

        self.running = True

        try:
            last_heartbeat = 0
            last_robot_check = 0
            heartbeat_interval = 5  # seconds
            robot_check_interval = 60  # seconds

            while self.running:
                current_time = asyncio.get_event_loop().time()

                # Send heartbeat periodically
                if current_time - last_heartbeat >= heartbeat_interval:
                    await self.send_heartbeat()
                    last_heartbeat = current_time

                # Check robot connection periodically
                if current_time - last_robot_check >= robot_check_interval:
                    await self.robot.check_connection()
                    await self.update_status()
                    last_robot_check = current_time

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Robot Edge Device interrupted by user")
        except Exception as e:
            logger.error("Unexpected error: %s", e)
        finally:
            self.running = False
            # Send offline status
            self.robot.processing = False
            await self.update_status()
            await self.nats.disconnect()


async def main():
    parser = argparse.ArgumentParser(
        description="Robot Edge Device - NATS.io version (modular for any robot type)"
    )
    parser.add_argument(
        "--nats-servers",
        nargs="+",
        default=["nats://localhost:4222"],
        help="NATS server URLs (default: nats://localhost:4222)",
    )
    parser.add_argument(
        "--device-type", default="opentrons", help="Device type (default: opentrons)"
    )
    parser.add_argument(
        "--device-id", help="Device ID (default: auto-generated from robot IP)"
    )
    parser.add_argument(
        "--robot-ip",
        default="192.168.50.64",
        help="Robot IP address (default: 192.168.50.64)",
    )
    parser.add_argument(
        "--robot-port", type=int, default=31950, help="Robot API port (default: 31950)"
    )
    parser.add_argument(
        "--api-base-url",
        help="Robot API base URL (default: http://<robot-ip>:<robot-port>)",
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=30,
        help="API request timeout in seconds (default: 30)",
    )

    args = parser.parse_args()

    # Generate device ID if not provided
    device_id = args.device_id
    if not device_id:
        device_id = f"ot2_{args.robot_ip.replace('.', '_')}"

    # Build connection_config based on device type
    # For IP-based robots (like Opentrons), use robot_ip and robot_port
    connection_config = {
        "robot_ip": args.robot_ip,
        "robot_port": args.robot_port,
    }
    if args.api_base_url:
        connection_config["api_base_url"] = args.api_base_url

    # Create robot configuration
    robot_config = RobotConfig(
        device_type=args.device_type,
        device_id=device_id,
        connection_config=connection_config,
        api_timeout=args.api_timeout,
    )

    # Create robot instance (currently only OpentronsRobot is implemented)
    # In the future, you could have: BearsRobot, OtherRobot, etc.
    if args.device_type == "opentrons":
        robot = OpentronsRobot(robot_config)
    else:
        logger.error("Unsupported device type: %s", args.device_type)
        logger.error("Currently only 'opentrons' is supported")
        sys.exit(1)

    # Create NATS client
    nats_client = NATSClient(servers=args.nats_servers, device_id=device_id)

    # Create and run edge device
    edge_device = RobotEdgeDevice(robot, nats_client)

    print("Starting Robot Edge Device")
    print(f"Device Type: {args.device_type}")
    print(f"Device ID: {device_id}")
    print(f"NATS Servers: {args.nats_servers}")
    print(f"Robot: {args.robot_ip}:{args.robot_port}")

    await edge_device.run()


if __name__ == "__main__":
    asyncio.run(main())
