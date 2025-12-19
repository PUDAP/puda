"""
Opentrons Robot Implementation
Specific implementation for Opentrons OT-2 robots
"""
import asyncio
import logging
import os
import tempfile
from typing import Dict, Any, Optional
import aiohttp

from base_robot import BaseMachine, MachineConfig

logger = logging.getLogger(__name__)


class OpentronsRobot(BaseMachine):
    """
    Opentrons OT-2 robot implementation.
    Handles Opentrons-specific API calls and protocol execution.
    """
    
    def __init__(self, config: MachineConfig):
        super().__init__(config)
        
        # Opentrons robots use IP-based HTTP API
        self.robot_ip = "192.168.50.64"
        self.robot_port = 31950
        self.api_base_url = f"http://{self.robot_ip}:{self.robot_port}"
        self._capabilities = ['liquid_handling', 'protocol_execution', 'real_robot_control', 'pipette_control']

        # Opentrons-specific API configuration
        self.api_headers = {"opentrons-version": "*"}
        
    @property
    def capabilities(self) -> list[str]:
        """Get Opentrons-specific capabilities"""
        return self._capabilities
    
    @capabilities.setter
    def capabilities(self, value: list[str]):
        """Set Opentrons-specific capabilities"""
        self._capabilities = value
    
    async def check_connection(self) -> bool:
        """Check if Opentrons robot is accessible"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_base_url}/health",
                    headers=self.api_headers,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        self.connected = True
                        logger.info("✅ Opentrons machine at %s is accessible", self.robot_ip)
                        return True
                    else:
                        self.connected = False
                        logger.warning(
                            "⚠️ Opentrons robot at %s returned status %s",
                            self.robot_ip,
                            response.status
                        )
                        return False
        except Exception as e:
            self.connected = False
            logger.error("❌ Cannot connect to Opentrons robot at %s: %s", self.robot_ip, e)
            return False
    
    def _preprocess_protocol_code(self, protocol_code: str) -> str:
        """Preprocess protocol code to fix common issues"""
        protocol_code = protocol_code.strip()
        
        # Ensure proper imports
        if "from opentrons import protocol_api" not in protocol_code:
            protocol_code = "from opentrons import protocol_api\n\n" + protocol_code
        
        # Fix common metadata issues
        if "metadata = {" in protocol_code and "protocolName" not in protocol_code:
            metadata_section = '''# metadata
metadata = {
    "protocolName": "MQTT Protocol",
    "author": "MQTT Edge Device",
    "description": "Protocol executed via MQTT"
}

# requirements
requirements = {
    "robotType": "OT-2",
    "apiLevel": "2.23"
}

'''
            if "def run(" not in protocol_code:
                protocol_code = metadata_section + protocol_code
            else:
                parts = protocol_code.split("def run(")
                if len(parts) == 2:
                    protocol_code = metadata_section + "def run(" + parts[1]
        
        return protocol_code
    
    async def _upload_protocol(
        self, 
        protocol_code: str, 
        protocol_filename: str = "mqtt_protocol.py"
    ) -> Optional[str]:
        """Upload protocol to Opentrons robot"""
        try:
            # Preprocess the protocol code
            processed_code = self._preprocess_protocol_code(protocol_code)
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                temp_file.write(processed_code)
                temp_file_path = temp_file.name
            
            try:
                # Upload protocol
                async with aiohttp.ClientSession() as session:
                    with open(temp_file_path, 'rb') as file_obj:
                        data = aiohttp.FormData()
                        data.add_field(
                            'files',
                            file_obj,
                            filename=protocol_filename,
                            content_type='text/x-python'
                        )
                        
                        protocol_url = f"{self.api_base_url}/protocols"
                        async with session.post(
                            protocol_url,
                            data=data,
                            headers=self.api_headers,
                            timeout=aiohttp.ClientTimeout(total=30)
                        ) as response:
                            if response.status not in (201, 200):
                                text = await response.text()
                                raise Exception(
                                    f"Failed to upload protocol. "
                                    f"Status: {response.status}, Response: {text}"
                                )
                            
                            result = await response.json()
                            protocol_id = result.get("data", {}).get("id")
                            if not protocol_id:
                                raise Exception("Protocol uploaded but no protocol ID returned")
                            
                            logger.info("✅ Protocol uploaded successfully. Protocol ID: %s", protocol_id)
                            return protocol_id
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
                    
        except Exception as e:
            logger.error("❌ Failed to upload protocol: %s", e)
            return None
    
    async def _create_and_start_run(self, protocol_id: str) -> Optional[str]:
        """Create and start a run on the Opentrons robot"""
        try:
            async with aiohttp.ClientSession() as session:
                # Create run
                runs_url = f"{self.api_base_url}/runs"
                run_payload = {"data": {"protocolId": protocol_id}}
                
                async with session.post(
                    runs_url,
                    json=run_payload,
                    headers=self.api_headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status not in (201, 200):
                        text = await response.text()
                        raise Exception(
                            f"Failed to create run. "
                            f"Status: {response.status}, Response: {text}"
                        )
                    
                    result = await response.json()
                    run_id = result.get("data", {}).get("id")
                    if not run_id:
                        raise Exception("Run created but no run ID returned")
                
                # Start run
                actions_url = f"{self.api_base_url}/runs/{run_id}/actions"
                action_payload = {"data": {"actionType": "play"}}
                
                async with session.post(
                    actions_url,
                    json=action_payload,
                    headers=self.api_headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status not in (201, 200):
                        text = await response.text()
                        raise Exception(
                            f"Failed to start run. "
                            f"Status: {response.status}, Response: {text}"
                        )
                
                logger.info("✅ Run started successfully. Run ID: %s", run_id)
                return run_id
                
        except Exception as e:
            logger.error("❌ Failed to create/start run: %s", e)
            return None
    
    async def _monitor_run_status(
        self, 
        run_id: str, 
        timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        """Monitor run status until completion"""
        try:
            status_url = f"{self.api_base_url}/runs/{run_id}"
            poll_interval = 3  # Check every 3 seconds
            elapsed_time = 0
            
            async with aiohttp.ClientSession() as session:
                while elapsed_time < timeout_seconds:
                    try:
                        async with session.get(
                            status_url,
                            headers=self.api_headers,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as response:
                            if response.status == 200:
                                result = await response.json()
                                run_data = result.get("data", {})
                                current_status = run_data.get("status", "unknown")
                                
                                logger.info(
                                    "Run %s status: %s (elapsed: %ss)",
                                    run_id,
                                    current_status,
                                    elapsed_time
                                )
                                
                                if current_status in ["succeeded", "failed", "stopped"]:
                                    return {
                                        "status": current_status,
                                        "run_id": run_id,
                                        "elapsed_time": elapsed_time,
                                        "run_data": run_data
                                    }
                        
                        await asyncio.sleep(poll_interval)
                        elapsed_time += poll_interval
                        
                    except Exception as e:
                        logger.warning("Error checking run status: %s", e)
                        await asyncio.sleep(poll_interval)
                        elapsed_time += poll_interval
                
                # Timeout reached
                return {
                    "status": "timeout",
                    "run_id": run_id,
                    "elapsed_time": elapsed_time,
                    "error": f"Run monitoring timed out after {timeout_seconds} seconds"
                }
                
        except Exception as e:
            logger.error("❌ Error monitoring run: %s", e)
            return {
                "status": "error",
                "run_id": run_id,
                "error": str(e)
            }
    
    async def validate_protocol(self, protocol_data: ProtocolData) -> Dict[str, Any]:
        """Validate protocol data for Opentrons execution"""
        errors = []
        
        # Check required fields
        if not protocol_data.protocol_code:
            errors.append("Missing protocol_code")
        
        # Check robot connection
        if not await self.check_connection():
            errors.append(f"Cannot connect to Opentrons robot at {self.robot_ip}")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    async def execute_protocol(self, protocol_data: ProtocolData) -> ExecutionResult:
        """Execute protocol asynchronously on real Opentrons robot"""
        try:
            self.processing = True
            
            logger.info("Starting protocol execution on Opentrons robot %s", self.robot_ip)
            
            # Upload protocol to robot
            protocol_id_robot = await self._upload_protocol(protocol_data.protocol_code)
            if not protocol_id_robot:
                raise Exception("Failed to upload protocol to robot")
            
            self.current_protocol_id = protocol_id_robot
            
            # Create and start run
            run_id = await self._create_and_start_run(protocol_id_robot)
            if not run_id:
                raise Exception("Failed to create/start run on robot")
            
            self.current_run_id = run_id
            
            # Monitor run status
            execution_result = await self._monitor_run_status(
                run_id, 
                protocol_data.timeout_seconds
            )
            
            # Process result
            if execution_result['status'] == 'succeeded':
                return ExecutionResult(
                    protocol_id=protocol_data.protocol_id,
                    status='succeeded',
                    run_id=execution_result.get('run_id'),
                    elapsed_time=execution_result.get('elapsed_time'),
                    results=execution_result
                )
            else:
                error_msg = execution_result.get(
                    'error', 
                    f"Protocol failed with status: {execution_result['status']}"
                )
                return ExecutionResult(
                    protocol_id=protocol_data.protocol_id,
                    status=execution_result['status'],
                    run_id=execution_result.get('run_id'),
                    elapsed_time=execution_result.get('elapsed_time'),
                    error=error_msg
                )
                
        except Exception as e:
            logger.error("Error in protocol execution: %s", e)
            return ExecutionResult(
                protocol_id=protocol_data.protocol_id,
                status='error',
                error=str(e)
            )
        finally:
            self.processing = False
            self.current_run_id = None
            self.current_protocol_id = None
    
    async def cancel_protocol(self, protocol_id: str) -> bool:
        """Cancel a running protocol"""
        # TODO: Implement cancel functionality for Opentrons
        # This would require calling the Opentrons API to stop the current run
        logger.warning("Cancel protocol not yet implemented for %s", protocol_id)
        return False
    
    async def get_robot_status(self) -> Dict[str, Any]:
        """Get current robot status - simplified for less verbose logging"""
        try:
            if not self.connected:
                return {
                    "status": "offline",
                    "robot_ip": self.robot_ip
                }
            
            # Get robot status from API
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_base_url}/health",
                    headers=self.api_headers,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        health_data = await response.json()
                        # Only include essential health info
                        simplified_health = {
                            'name': health_data.get('name', 'Unknown'),
                            'robot_model': health_data.get('robot_model', 'Unknown'),
                            'api_version': health_data.get('api_version', 'Unknown'),
                            'status': 'online'
                        }
                        return {
                            "status": "online",
                            "robot_ip": self.robot_ip,
                            "health": simplified_health,
                            "processing": self.processing,
                            "current_run_id": self.current_run_id,
                            "current_protocol_id": self.current_protocol_id
                        }
                    else:
                        return {
                            "status": "error",
                            "robot_ip": self.robot_ip,
                            "error": f"Health check failed: {response.status}"
                        }
        except Exception as e:
            return {
                "status": "error",
                "robot_ip": self.robot_ip,
                "error": str(e)
            }

