#!/usr/bin/env python3
"""
Opentrons Edge Device
Real Opentrons OT-2 robot interface via NATS communication
Extends base EdgeDevice with Opentrons-specific functionality
"""

import time
import logging
import os
import tempfile
import requests
from typing import Dict, Any, Optional
import sys

# Add the library to the path for imports
workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
lib_path = os.path.join(workspace_root, "libs", "edge-device")
sys.path.insert(0, lib_path)

from edge_device import EdgeDevice  # noqa: E402

logger = logging.getLogger(__name__)


class OpentronsEdgeDevice(EdgeDevice):
    """Opentrons-specific edge device implementation"""

    def __init__(
        self,
        robot_ip: str = "192.168.50.64",
        robot_port: int = 31950,
        nats_servers: list = None,
        **kwargs,
    ):
        """
        Initialize Opentrons edge device

        Args:
            robot_ip: Opentrons robot IP address
            robot_port: Opentrons robot API port
            nats_servers: List of NATS server URLs
            **kwargs: Additional arguments passed to base EdgeDevice
        """
        self.robot_ip = robot_ip
        self.robot_port = robot_port

        # Generate device ID if not provided
        device_id = kwargs.get("device_id") or f"opentrons_{robot_ip.replace('.', '_')}"
        device_type = kwargs.get("device_type") or "opentrons"
        device_name = kwargs.get("device_name") or f"Opentrons Robot {robot_ip}"

        # Opentrons-specific capabilities
        capabilities = kwargs.get("capabilities") or [
            "liquid_handling",
            "protocol_execution",
            "real_robot_control",
            "pipette_control",
        ]

        # Connection info
        connection_info = {
            "robot_ip": self.robot_ip,
            "robot_port": self.robot_port,
            **kwargs.get("connection_info", {}),
        }

        # Initialize base class
        super().__init__(
            device_id=device_id,
            device_type=device_type,
            device_name=device_name,
            nats_servers=nats_servers,
            capabilities=capabilities,
            connection_info=connection_info,
        )

        # Opentrons API configuration
        self.api_base_url = f"http://{self.robot_ip}:{self.robot_port}"
        self.headers = {"opentrons-version": "*"}

        # Protocol execution tracking
        self.current_protocol_id = None
        self.current_run_id = None
        self.robot_connected = False

    async def check_device_connection(self) -> bool:
        """Check if Opentrons robot is accessible"""
        try:
            response = requests.get(
                f"{self.api_base_url}/health", headers=self.headers, timeout=5
            )
            if response.status_code == 200:
                self.robot_connected = True
                logger.info(f"✅ Opentrons robot at {self.robot_ip} is accessible")
                return True
            else:
                self.robot_connected = False
                logger.warning(
                    f"⚠️ Opentrons robot at {self.robot_ip} returned status {response.status_code}"
                )
                return False
        except Exception as e:
            self.robot_connected = False
            logger.error(
                f"❌ Cannot connect to Opentrons robot at {self.robot_ip}: {e}"
            )
            return False

    async def initialize_device(self):
        """Initialize Opentrons device on startup"""
        logger.info(f"Checking connection to Opentrons robot at {self.robot_ip}...")
        if not await self.check_device_connection():
            logger.warning(
                f"⚠️ Opentrons robot at {self.robot_ip} is not accessible"
            )
            logger.warning(
                "The edge device will continue running but protocol execution will fail"
            )
        else:
            logger.info(f"✅ Opentrons robot at {self.robot_ip} is accessible")

        # Update connection info
        self.connection_info["robot_connected"] = self.robot_connected

    def preprocess_protocol_code(self, protocol_code: str) -> str:
        """Preprocess protocol code to fix common issues"""
        # Remove any leading/trailing whitespace
        protocol_code = protocol_code.strip()

        # Ensure proper imports
        if "from opentrons import protocol_api" not in protocol_code:
            protocol_code = "from opentrons import protocol_api\n\n" + protocol_code

        # Fix common metadata issues
        if "metadata = {" in protocol_code and "protocolName" not in protocol_code:
            # Add basic metadata if missing
            metadata_section = """# metadata
metadata = {
    "protocolName": "MQTT Protocol",
    "author": "MQTT Edge Device",
    "description": "Protocol executed via NATS"
}

# requirements
requirements = {
    "robotType": "OT-2",
    "apiLevel": "2.23"
}

"""
            if "def run(" not in protocol_code:
                protocol_code = metadata_section + protocol_code
            else:
                # Insert metadata before the run function
                parts = protocol_code.split("def run(")
                if len(parts) == 2:
                    protocol_code = metadata_section + "def run(" + parts[1]

        return protocol_code

    def upload_protocol(
        self, protocol_code: str, protocol_filename: str = "nats_protocol.py"
    ) -> Optional[str]:
        """Upload protocol to Opentrons robot"""
        try:
            # Preprocess the protocol code
            processed_code = self.preprocess_protocol_code(protocol_code)

            # Create temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as temp_file:
                temp_file.write(processed_code)
                temp_file_path = temp_file.name

            try:
                # Upload protocol
                with open(temp_file_path, "rb") as file_obj:
                    files = {"files": (protocol_filename, file_obj, "text/x-python")}
                    protocol_url = f"{self.api_base_url}/protocols"
                    upload_response = requests.post(
                        protocol_url, files=files, headers=self.headers, timeout=30
                    )

                if upload_response.status_code not in (201, 200):
                    raise Exception(
                        f"Failed to upload protocol. Status: {upload_response.status_code}, Response: {upload_response.text}"
                    )

                protocol_id = upload_response.json().get("data", {}).get("id")
                if not protocol_id:
                    raise Exception("Protocol uploaded but no protocol ID returned")

                logger.info(
                    f"✅ Protocol uploaded successfully. Protocol ID: {protocol_id}"
                )
                return protocol_id

            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"❌ Failed to upload protocol: {e}")
            return None

    def create_and_start_run(self, protocol_id: str) -> Optional[str]:
        """Create and start a run on the Opentrons robot"""
        try:
            # Create run
            runs_url = f"{self.api_base_url}/runs"
            run_payload = {"data": {"protocolId": protocol_id}}
            run_response = requests.post(
                runs_url, json=run_payload, headers=self.headers, timeout=30
            )

            if run_response.status_code not in (201, 200):
                raise Exception(
                    f"Failed to create run. Status: {run_response.status_code}, Response: {run_response.text}"
                )

            run_id = run_response.json().get("data", {}).get("id")
            if not run_id:
                raise Exception("Run created but no run ID returned")

            # Start run
            actions_url = f"{self.api_base_url}/runs/{run_id}/actions"
            action_payload = {"data": {"actionType": "play"}}
            action_response = requests.post(
                actions_url, json=action_payload, headers=self.headers, timeout=30
            )

            if action_response.status_code not in (201, 200):
                raise Exception(
                    f"Failed to start run. Status: {action_response.status_code}, Response: {action_response.text}"
                )

            logger.info(f"✅ Run started successfully. Run ID: {run_id}")
            return run_id

        except Exception as e:
            logger.error(f"❌ Failed to create/start run: {e}")
            return None

    def monitor_run_status(
        self, run_id: str, timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        """Monitor run status until completion"""
        try:
            status_url = f"{self.api_base_url}/runs/{run_id}"
            poll_interval = 3  # Check every 3 seconds
            elapsed_time = 0

            while elapsed_time < timeout_seconds:
                try:
                    status_response = requests.get(
                        status_url, headers=self.headers, timeout=10
                    )
                    if status_response.status_code == 200:
                        run_data = status_response.json().get("data", {})
                        current_status = run_data.get("status", "unknown")

                        logger.info(
                            f"Run {run_id} status: {current_status} (elapsed: {elapsed_time}s)"
                        )

                        if current_status in ["succeeded", "failed", "stopped"]:
                            return {
                                "status": current_status,
                                "run_id": run_id,
                                "elapsed_time": elapsed_time,
                                "run_data": run_data,
                            }

                    time.sleep(poll_interval)
                    elapsed_time += poll_interval

                except Exception as e:
                    logger.warning(f"Error checking run status: {e}")
                    time.sleep(poll_interval)
                    elapsed_time += poll_interval

            # Timeout reached
            return {
                "status": "timeout",
                "run_id": run_id,
                "elapsed_time": elapsed_time,
                "error": f"Run monitoring timed out after {timeout_seconds} seconds",
            }

        except Exception as e:
            logger.error(f"❌ Error monitoring run: {e}")
            return {"status": "error", "run_id": run_id, "error": str(e)}

    # Implement abstract methods from EdgeDevice

    async def validate_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate protocol data for Opentrons execution"""
        errors = []

        # Check required fields
        if not task_data.get("protocol_code"):
            errors.append("Missing protocol_code")

        # Check robot connection
        if not await self.check_device_connection():
            errors.append(f"Cannot connect to Opentrons robot at {self.robot_ip}")

        return {"valid": len(errors) == 0, "errors": errors}

    async def execute_task_async(self, task_id: str, task_data: Dict[str, Any]):
        """Execute protocol asynchronously on real Opentrons robot"""
        try:
            # Extract protocol code
            protocol_code = task_data.get("protocol_code")
            if not protocol_code:
                raise Exception("No protocol code provided")

            logger.info(
                f"Starting protocol execution on Opentrons robot {self.robot_ip}"
            )

            # Upload protocol to robot
            protocol_id_robot = self.upload_protocol(protocol_code)
            if not protocol_id_robot:
                raise Exception("Failed to upload protocol to robot")

            self.current_protocol_id = protocol_id_robot

            # Create and start run
            run_id = self.create_and_start_run(protocol_id_robot)
            if not run_id:
                raise Exception("Failed to create/start run on robot")

            self.current_run_id = run_id

            # Monitor run status
            timeout_seconds = task_data.get("timeout_seconds", 300)
            execution_result = self.monitor_run_status(run_id, timeout_seconds)

            # Process result
            if execution_result["status"] == "succeeded":
                await self.send_task_complete(task_id, execution_result)
            else:
                error_msg = execution_result.get(
                    "error",
                    f"Protocol failed with status: {execution_result['status']}",
                )
                await self.send_task_failed(task_id, error_msg)

        except Exception as e:
            logger.error(f"Error in protocol execution: {e}")
            await self.send_task_failed(task_id, str(e))
        finally:
            # Update device status
            self.processing = False
            self.current_run_id = None
            self.current_protocol_id = None
            self.current_task_id = None
            await self.send_status_update("online")

    async def cancel_task(self, task_id: str):
        """Cancel a running task on Opentrons robot"""
        try:
            if self.current_run_id:
                # Stop the run
                actions_url = f"{self.api_base_url}/runs/{self.current_run_id}/actions"
                action_payload = {"data": {"actionType": "stop"}}
                action_response = requests.post(
                    actions_url, json=action_payload, headers=self.headers, timeout=30
                )

                if action_response.status_code in (201, 200):
                    logger.info(f"✅ Run {self.current_run_id} stopped successfully")
                else:
                    logger.warning(
                        f"⚠️ Failed to stop run. Status: {action_response.status_code}"
                    )

        except Exception as e:
            logger.error(f"Error cancelling task: {e}")

    async def get_device_status(self) -> Dict[str, Any]:
        """Get current robot status"""
        try:
            if not self.robot_connected:
                return {"status": "offline", "robot_ip": self.robot_ip}

            # Get robot status from API
            response = requests.get(
                f"{self.api_base_url}/health", headers=self.headers, timeout=5
            )
            if response.status_code == 200:
                health_data = response.json()
                # Only include essential health info
                simplified_health = {
                    "name": health_data.get("name", "Unknown"),
                    "robot_model": health_data.get("robot_model", "Unknown"),
                    "api_version": health_data.get("api_version", "Unknown"),
                    "status": "online",
                }
                return {
                    "status": "online",
                    "robot_ip": self.robot_ip,
                    "health": simplified_health,
                    "processing": self.processing,
                    "current_run_id": self.current_run_id,
                    "current_protocol_id": self.current_protocol_id,
                }
            else:
                return {
                    "status": "error",
                    "robot_ip": self.robot_ip,
                    "error": f"Health check failed: {response.status_code}",
                }
        except Exception as e:
            return {"status": "error", "robot_ip": self.robot_ip, "error": str(e)}

