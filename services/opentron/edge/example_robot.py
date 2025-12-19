"""
Example: How to create a new robot implementation

This file shows how to implement a new robot type by extending BaseRobot.
You can use this as a template for implementing other robots (e.g., BearsRobot, CustomRobot, etc.)
"""
import asyncio
import logging
from typing import Dict, Any, Optional
import aiohttp

from base_robot import BaseRobot, RobotConfig, ProtocolData, ExecutionResult

logger = logging.getLogger(__name__)


class ExampleRobot(BaseRobot):
    """
    Example robot implementation.
    Replace this with your robot-specific API calls.
    """
    
    def __init__(self, config: RobotConfig):
        super().__init__(config)
        # Add robot-specific initialization here
        # e.g., custom API headers, authentication tokens, etc.
    
    async def check_connection(self) -> bool:
        """Check if robot is accessible"""
        try:
            # Extract connection details from connection_config
            # Example: For IP-based robots
            # robot_ip = self.config.connection_config.get('robot_ip')
            # api_base_url = self.config.connection_config.get('api_base_url', f"http://{robot_ip}:8080")
            
            # Example: For serial-based robots
            # serial_port = self.config.connection_config.get('serial_port')
            # baud_rate = self.config.connection_config.get('baud_rate', 9600)
            
            # Example: For ROS-based robots
            # ros_topic = self.config.connection_config.get('ros_topic')
            # ros_node = self.config.connection_config.get('ros_node')
            
            # Replace with your robot's health check
            # For IP-based example:
            api_base_url = self.config.connection_config.get('api_base_url', 'http://localhost:8080')
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{api_base_url}/health",
                    headers=self.config.api_headers or {},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        self.robot_connected = True
                        conn_str = str(self.config.connection_config)
                        logger.info("✅ Robot at %s is accessible", conn_str)
                        return True
                    else:
                        self.robot_connected = False
                        return False
        except Exception as e:
            self.robot_connected = False
            logger.error("❌ Cannot connect to robot: %s", e)
            return False
    
    async def validate_protocol(self, protocol_data: ProtocolData) -> Dict[str, Any]:
        """Validate protocol data"""
        errors = []
        
        # Add your validation logic here
        if not protocol_data.protocol_code:
            errors.append("Missing protocol_code")
        
        if not await self.check_connection():
            conn_str = str(self.config.connection_config)
            errors.append(f"Cannot connect to robot: {conn_str}")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    async def execute_protocol(self, protocol_data: ProtocolData) -> ExecutionResult:
        """Execute protocol on robot"""
        try:
            self.processing = True
            
            # Replace with your robot's protocol execution logic
            # Example steps:
            # 1. Upload/validate protocol
            # 2. Start execution
            # 3. Monitor progress
            # 4. Return results
            
            logger.info("Executing protocol %s", protocol_data.protocol_id)
            
            # Example: Make API call to start protocol
            # Extract connection details from connection_config
            api_base_url = self.config.connection_config.get('api_base_url', 'http://localhost:8080')
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{api_base_url}/protocols/execute",  # Your robot's execute endpoint
                    json={
                        "protocol_id": protocol_data.protocol_id,
                        "protocol_code": protocol_data.protocol_code
                    },
                    headers=self.config.api_headers or {},
                    timeout=aiohttp.ClientTimeout(total=self.config.api_timeout)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return ExecutionResult(
                            protocol_id=protocol_data.protocol_id,
                            status='succeeded',
                            results=result
                        )
                    else:
                        error_text = await response.text()
                        return ExecutionResult(
                            protocol_id=protocol_data.protocol_id,
                            status='failed',
                            error=f"API returned {response.status}: {error_text}"
                        )
            
        except Exception as e:
            logger.error("Error executing protocol: %s", e)
            return ExecutionResult(
                protocol_id=protocol_data.protocol_id,
                status='error',
                error=str(e)
            )
        finally:
            self.processing = False
    
    async def cancel_protocol(self, protocol_id: str) -> bool:
        """Cancel a running protocol"""
        try:
            # Replace with your robot's cancel endpoint
            api_base_url = self.config.connection_config.get('api_base_url', 'http://localhost:8080')
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{api_base_url}/protocols/{protocol_id}/cancel",
                    headers=self.config.api_headers or {},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
        except Exception as e:
            logger.error("Error cancelling protocol: %s", e)
            return False
    
    async def get_robot_status(self) -> Dict[str, Any]:
        """Get current robot status"""
        try:
            if not self.robot_connected:
                return {
                    "status": "offline",
                    "robot_ip": self.config.robot_ip
                }
            
            # Replace with your robot's status endpoint
            api_base_url = self.config.connection_config.get('api_base_url', 'http://localhost:8080')
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{api_base_url}/status",  # Your robot's status endpoint
                    headers=self.config.api_headers or {},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        status_data = await response.json()
                        return {
                            "status": "online",
                            "connection_config": self.config.connection_config,
                            **status_data
                        }
                    else:
                        return {
                            "status": "error",
                            "connection_config": self.config.connection_config,
                            "error": f"Status check failed: {response.status}"
                        }
        except Exception as e:
            return {
                "status": "error",
                "connection_config": self.config.connection_config,
                "error": str(e)
            }
    
    def get_capabilities(self) -> list[str]:
        """Return robot-specific capabilities"""
        return [
            'protocol_execution',
            # Add your robot's specific capabilities here
            # e.g., 'liquid_handling', 'gripper_control', etc.
        ]


# To use this robot, update main.py:
# 
# if args.device_type == 'opentrons':
#     robot = OpentronsRobot(robot_config)
# elif args.device_type == 'example':
#     robot = ExampleRobot(robot_config)
# else:
#     logger.error(f"Unsupported device type: {args.device_type}")
#     sys.exit(1)

