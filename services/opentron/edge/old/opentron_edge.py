#!/usr/bin/env python3
"""
Opentrons Edge Device
Real Opentrons OT-2 robot interface via MQTT communication
Executes protocols received via MQTT and reports results back
"""

import json
import time
import threading
import uuid
import logging
import os
import tempfile
import requests
from datetime import datetime
from typing import Dict, Any, Optional
import paho.mqtt.client as mqtt
import argparse
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OpentronsEdgeDevice:
    def __init__(self, broker_host: str = "192.168.50.131", broker_port: int = 8883, 
                 use_tls: bool = True, ca_cert_path: str = "ca.crt", 
                 robot_ip: str = "192.168.50.64", robot_port: int = 31950):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.use_tls = use_tls
        self.ca_cert_path = ca_cert_path
        self.robot_ip = robot_ip
        self.robot_port = robot_port
        
        # Device configuration
        self.device_id = f"opentrons_{robot_ip.replace('.', '_')}"
        self.client_id = f"opentrons-edge-{self.device_id}"
        
        # Topics - Updated to match MQTT server patterns
        self.protocol_topic = f"lab/{self.device_id}/protocols"  # Listen to protocol commands
        # Ping topic removed - using status updates instead
        self.cancel_topic = f"lab/{self.device_id}/cancel"  # Listen to cancel commands
        self.response_topic = f"lab/{self.device_id}/response"  # Send responses
        self.status_topic = f"lab/{self.device_id}/status"  # Send status updates
        self.heartbeat_topic = f"lab/{self.device_id}/heartbeat"  # Send heartbeat
        self.protocol_complete_topic = f"lab/{self.device_id}/protocol_complete"  # Send completion
        self.protocol_failed_topic = f"lab/{self.device_id}/protocol_failed"  # Send failures
        
        # Opentrons API configuration
        self.api_base_url = f"http://{self.robot_ip}:{self.robot_port}"
        self.headers = {"opentrons-version": "*"}
        
        # Protocol execution tracking
        self.current_run_id = None
        self.current_protocol_id = None
        
        # Device state
        self.connected = False
        self.processing = False
        self.experiment_history = []
        self.robot_connected = False
        
        # Initialize MQTT client
        self.client = mqtt.Client(client_id=self.client_id)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        
        # Setup TLS connection
        self._setup_tls_connection()

    def _setup_tls_connection(self):
        """Setup TLS connection with multiple fallback methods for Windows compatibility"""
        if not self.use_tls:
            return
            
        import ssl
        
        if self.ca_cert_path and os.path.exists(self.ca_cert_path):
            # Method 1: Try standard SSL context with certificate
            try:
                ssl_context = ssl.create_default_context(cafile=self.ca_cert_path)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                
                # Windows-specific fixes
                try:
                    ssl_context.set_ciphers('DEFAULT:@SECLEVEL=1')
                except (AttributeError, ssl.SSLError):
                    pass
                
                try:
                    ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
                    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                except (AttributeError, ssl.SSLError):
                    try:
                        ssl_context.options |= ssl.OP_NO_TLSv1_3
                    except (AttributeError, ssl.SSLError):
                        pass
                
                self.client.tls_set_context(ssl_context)
                logger.info(f"🔒 Method 1: Using CA certificate with standard SSL context: {self.ca_cert_path}")
                return
                
            except Exception as e:
                logger.warning(f"⚠️ Method 1 failed: {e}")
            
            # Method 2: Try permissive SSL context
            try:
                ssl_context = ssl.create_default_context()
                ssl_context.load_verify_locations(cafile=self.ca_cert_path)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                self.client.tls_set_context(ssl_context)
                logger.info(f"🔒 Method 2: Using CA certificate with permissive SSL context: {self.ca_cert_path}")
                return
                
            except Exception as e:
                logger.warning(f"⚠️ Method 2 failed: {e}")
            
            # Method 3: Try paho-mqtt's built-in TLS with CA file
            try:
                self.client.tls_set(ca_certs=self.ca_cert_path, certfile=None, keyfile=None, 
                                  cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS, 
                                  ciphers=None)
                self.client.tls_insecure_set(True)  # Don't verify hostname
                logger.info(f"🔒 Method 3: Using built-in TLS with CA certificate: {self.ca_cert_path}")
                return
                
            except Exception as e:
                logger.warning(f"⚠️ Method 3 failed: {e}")
            
            # Method 4: Try insecure TLS with CA (ignore certificate errors)
            try:
                self.client.tls_set()
                self.client.tls_insecure_set(True)
                logger.warning(f"⚠️ Method 4: Using insecure TLS (ignoring certificate validation)")
                return
                
            except Exception as e:
                logger.error(f"❌ Method 4 failed: {e}")
        
        else:
            # No CA certificate provided or file doesn't exist
            try:
                self.client.tls_set()
                self.client.tls_insecure_set(True)
                logger.warning(f"⚠️ CA certificate not found at {self.ca_cert_path}, using insecure TLS")
                return
            except Exception as e:
                logger.error(f"❌ Failed to setup any TLS connection: {e}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"Device {self.device_id} connected to MQTT broker")
            self.connected = True
            
            # Subscribe to device-specific topics
            topics = [
                (self.protocol_topic, 1),
                (self.cancel_topic, 1)
            ]
            
            for topic, qos in topics:
                result = client.subscribe(topic, qos)
                logger.info(f"Subscribed to {topic} with QoS {qos}")
            
            # Send initial status and heartbeat
            self.send_status_update("online")
            self.send_heartbeat()
            
        else:
            logger.error(f"Failed to connect to MQTT broker. Return code: {rc}")

    def on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection. Return code: {rc}")
        else:
            logger.info("Disconnected from MQTT broker")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            logger.info(f"Received message on {msg.topic}: {payload}")
            
            # Route message based on topic
            if msg.topic == self.protocol_topic:
                self.handle_protocol_message(payload)
            elif msg.topic == self.cancel_topic:
                self.handle_cancel_message(payload)
            else:
                logger.warning(f"Unknown topic: {msg.topic}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def handle_protocol_message(self, payload: Dict[str, Any]):
        """Handle protocol execution messages"""
        try:
            protocol_id = payload.get('protocol_id')
            protocol_data = payload.get('protocol_data', {})
            
            logger.info(f"Executing protocol {protocol_id}")
            
            # Update device status
            self.processing = True
            self.send_status_update("busy")
            
            # Validate protocol
            validation_result = self.validate_protocol(protocol_data)
            if not validation_result['valid']:
                self.send_protocol_failed(protocol_id, validation_result['errors'])
                return
            
            # Execute protocol in background thread
            import threading
            thread = threading.Thread(
                target=self.execute_protocol_async,
                args=(protocol_id, protocol_data),
                daemon=True
            )
            thread.start()
            
        except Exception as e:
            logger.error(f"Error handling protocol message: {e}")
            self.send_protocol_failed(payload.get('protocol_id'), str(e))
    
    def check_robot_connection(self) -> bool:
        """Check if Opentrons robot is accessible"""
        try:
            response = requests.get(f"{self.api_base_url}/health", headers=self.headers, timeout=5)
            if response.status_code == 200:
                self.robot_connected = True
                logger.info(f"✅ Opentrons robot at {self.robot_ip} is accessible")
                return True
            else:
                self.robot_connected = False
                logger.warning(f"⚠️ Opentrons robot at {self.robot_ip} returned status {response.status_code}")
                return False
        except Exception as e:
            self.robot_connected = False
            logger.error(f"❌ Cannot connect to Opentrons robot at {self.robot_ip}: {e}")
            return False
    
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
                # Insert metadata before the run function
                parts = protocol_code.split("def run(")
                if len(parts) == 2:
                    protocol_code = metadata_section + "def run(" + parts[1]
        
        return protocol_code
    
    def upload_protocol(self, protocol_code: str, protocol_filename: str = "mqtt_protocol.py") -> Optional[str]:
        """Upload protocol to Opentrons robot"""
        try:
            # Preprocess the protocol code
            processed_code = self.preprocess_protocol_code(protocol_code)
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                temp_file.write(processed_code)
                temp_file_path = temp_file.name
            
            try:
                # Upload protocol
                with open(temp_file_path, 'rb') as file_obj:
                    files = {
                        'files': (protocol_filename, file_obj, 'text/x-python')
                    }
                    protocol_url = f"{self.api_base_url}/protocols"
                    upload_response = requests.post(protocol_url, files=files, headers=self.headers, timeout=30)
                
                if upload_response.status_code not in (201, 200):
                    raise Exception(f"Failed to upload protocol. Status: {upload_response.status_code}, Response: {upload_response.text}")
                
                protocol_id = upload_response.json().get("data", {}).get("id")
                if not protocol_id:
                    raise Exception("Protocol uploaded but no protocol ID returned")
                
                logger.info(f"✅ Protocol uploaded successfully. Protocol ID: {protocol_id}")
                return protocol_id
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except:
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
            run_response = requests.post(runs_url, json=run_payload, headers=self.headers, timeout=30)
            
            if run_response.status_code not in (201, 200):
                raise Exception(f"Failed to create run. Status: {run_response.status_code}, Response: {run_response.text}")
            
            run_id = run_response.json().get("data", {}).get("id")
            if not run_id:
                raise Exception("Run created but no run ID returned")
            
            # Start run
            actions_url = f"{self.api_base_url}/runs/{run_id}/actions"
            action_payload = {"data": {"actionType": "play"}}
            action_response = requests.post(actions_url, json=action_payload, headers=self.headers, timeout=30)
            
            if action_response.status_code not in (201, 200):
                raise Exception(f"Failed to start run. Status: {action_response.status_code}, Response: {action_response.text}")
            
            logger.info(f"✅ Run started successfully. Run ID: {run_id}")
            return run_id
            
        except Exception as e:
            logger.error(f"❌ Failed to create/start run: {e}")
            return None
    
    def monitor_run_status(self, run_id: str, timeout_seconds: int = 300) -> Dict[str, Any]:
        """Monitor run status until completion"""
        try:
            status_url = f"{self.api_base_url}/runs/{run_id}"
            poll_interval = 3  # Check every 3 seconds
            elapsed_time = 0
            
            while elapsed_time < timeout_seconds:
                try:
                    status_response = requests.get(status_url, headers=self.headers, timeout=10)
                    if status_response.status_code == 200:
                        run_data = status_response.json().get("data", {})
                        current_status = run_data.get("status", "unknown")
                        
                        logger.info(f"Run {run_id} status: {current_status} (elapsed: {elapsed_time}s)")
                        
                        if current_status in ["succeeded", "failed", "stopped"]:
                            return {
                                "status": current_status,
                                "run_id": run_id,
                                "elapsed_time": elapsed_time,
                                "run_data": run_data
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
                "error": f"Run monitoring timed out after {timeout_seconds} seconds"
            }
            
        except Exception as e:
            logger.error(f"❌ Error monitoring run: {e}")
            return {
                "status": "error",
                "run_id": run_id,
                "error": str(e)
            }
    
    def handle_cancel_message(self, payload: Dict[str, Any]):
        """Handle protocol cancellation messages"""
        try:
            protocol_id = payload.get('protocol_id')
            logger.info(f"Cancelling protocol {protocol_id}")
            
            # Update device status
            self.processing = False
            self.send_status_update("online")
            
            # Send cancellation response
            response = {
                'protocol_id': protocol_id,
                'device_id': self.device_id,
                'timestamp': datetime.now().isoformat(),
                'status': 'cancelled',
                'message': f'Protocol {protocol_id} cancelled by {self.device_id}'
            }
            
            self.client.publish(self.response_topic, json.dumps(response), qos=1)
            logger.info(f"Sent cancellation response to {self.response_topic}")
            
        except Exception as e:
            logger.error(f"Error handling cancel message: {e}")
    
    def execute_protocol_async(self, protocol_id: str, protocol_data: Dict[str, Any]):
        """Execute protocol asynchronously on real Opentrons robot"""
        try:
            # Extract protocol code
            protocol_code = protocol_data.get('protocol_code')
            if not protocol_code:
                raise Exception("No protocol code provided")
            
            logger.info(f"Starting protocol execution on Opentrons robot {self.robot_ip}")
            
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
            timeout_seconds = protocol_data.get('timeout_seconds', 300)
            execution_result = self.monitor_run_status(run_id, timeout_seconds)
            
            # Process result
            if execution_result['status'] == 'succeeded':
                self.send_protocol_complete(protocol_id, execution_result)
            else:
                error_msg = execution_result.get('error', f"Protocol failed with status: {execution_result['status']}")
                self.send_protocol_failed(protocol_id, error_msg)
                
        except Exception as e:
            logger.error(f"Error in protocol execution: {e}")
            self.send_protocol_failed(protocol_id, str(e))
        finally:
            # Update device status
            self.processing = False
            self.current_run_id = None
            self.current_protocol_id = None
            self.send_status_update("online")
    
    def send_status_update(self, status: str):
        """Send status update with comprehensive device information for auto-registration"""
        try:
            robot_status = self.get_robot_status()
            message = {
                'device_id': self.device_id,
                'device_type': 'opentrons',
                'device_name': f"Opentrons Robot {self.robot_ip}",
                'status': status,
                'timestamp': datetime.now().isoformat(),
                'processing': self.processing,
                'robot_ip': self.robot_ip,
                'robot_status': robot_status,
                'current_run_id': self.current_run_id,
                'current_protocol_id': self.current_protocol_id,
                'capabilities': ['liquid_handling', 'protocol_execution', 'real_robot_control', 'pipette_control'],
                'connection_info': {
                    'robot_ip': self.robot_ip,
                    'robot_port': self.robot_port,
                    'mqtt_connected': self.connected,
                    'robot_connected': self.robot_connected
                }
            }
            
            self.client.publish(self.status_topic, json.dumps(message), qos=1)
            logger.info(f"Sent status update: {status} (Robot: {robot_status['status']})")
            
        except Exception as e:
            logger.error(f"Error sending status update: {e}")
    
    def send_heartbeat(self):
        """Send heartbeat message with comprehensive device information for auto-registration"""
        try:
            robot_status = self.get_robot_status()
            message = {
                'device_id': self.device_id,
                'device_type': 'opentrons',
                'device_name': f"Opentrons Robot {self.robot_ip}",
                'status': 'online',
                'timestamp': datetime.now().isoformat(),
                'processing': self.processing,
                'robot_ip': self.robot_ip,
                'robot_status': robot_status,
                'current_run_id': self.current_run_id,
                'current_protocol_id': self.current_protocol_id,
                'capabilities': ['liquid_handling', 'protocol_execution', 'real_robot_control', 'pipette_control'],
                'connection_info': {
                    'robot_ip': self.robot_ip,
                    'robot_port': self.robot_port,
                    'mqtt_connected': self.connected,
                    'robot_connected': self.robot_connected
                }
            }
            
            self.client.publish(self.heartbeat_topic, json.dumps(message), qos=1)
            logger.debug(f"Sent heartbeat (Robot: {robot_status['status']})")
            
        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")
    
    def send_protocol_complete(self, protocol_id: str, results: Dict[str, Any]):
        """Send protocol completion message"""
        try:
            message = {
                'protocol_id': protocol_id,
                'device_id': self.device_id,
                'device_type': 'opentrons',
                'status': 'completed',
                'timestamp': datetime.now().isoformat(),
                'robot_ip': self.robot_ip,
                'run_id': results.get('run_id'),
                'elapsed_time': results.get('elapsed_time'),
                'results': results
            }
            
            self.client.publish(self.protocol_complete_topic, json.dumps(message), qos=1)
            logger.info(f"Sent protocol completion for {protocol_id} (Run: {results.get('run_id')})")
            
        except Exception as e:
            logger.error(f"Error sending protocol completion: {e}")
    
    def send_protocol_failed(self, protocol_id: str, error: str):
        """Send protocol failure message"""
        try:
            message = {
                'protocol_id': protocol_id,
                'device_id': self.device_id,
                'device_type': 'opentrons',
                'status': 'failed',
                'timestamp': datetime.now().isoformat(),
                'robot_ip': self.robot_ip,
                'run_id': self.current_run_id,
                'error': error
            }
            
            self.client.publish(self.protocol_failed_topic, json.dumps(message), qos=1)
            logger.error(f"Sent protocol failure for {protocol_id}: {error}")
            
        except Exception as e:
            logger.error(f"Error sending protocol failure: {e}")

    def get_device_info(self) -> Dict[str, Any]:
        """Get device information"""
        return {
            'device_id': self.device_id,
            'device_type': 'opentrons',
            'robot_ip': self.robot_ip,
            'robot_port': self.robot_port,
            'mqtt_connected': self.connected,
            'robot_connected': self.robot_connected,
            'processing': self.processing,
            'current_run_id': self.current_run_id,
            'current_protocol_id': self.current_protocol_id
        }

    def validate_protocol(self, protocol_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate protocol data for Opentrons execution"""
        
        errors = []
        
        # Check required fields
        if not protocol_data.get('protocol_code'):
            errors.append("Missing protocol_code")
        
        # Check robot connection
        if not self.check_robot_connection():
            errors.append(f"Cannot connect to Opentrons robot at {self.robot_ip}")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }

    def get_robot_status(self) -> Dict[str, Any]:
        """Get current robot status - simplified for less verbose logging"""
        try:
            if not self.robot_connected:
                return {
                    "status": "offline",
                    "robot_ip": self.robot_ip
                }
            
            # Get robot status from API
            response = requests.get(f"{self.api_base_url}/health", headers=self.headers, timeout=5)
            if response.status_code == 200:
                health_data = response.json()
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
                    "error": f"Health check failed: {response.status_code}"
                }
        except Exception as e:
            return {
                "status": "error",
                "robot_ip": self.robot_ip,
                "error": str(e)
            }

    def connect(self) -> bool:
        """Connect to MQTT broker with enhanced error handling"""
        try:
            logger.info(f"Device {self.device_id} connecting to MQTT broker {self.broker_host}:{self.broker_port}")
            
            # Try connection with current TLS setup
            try:
                self.client.connect(self.broker_host, self.broker_port, 60)
                self.client.loop_start()
                
                # Wait for connection
                timeout = 10
                start_time = time.time()
                while not self.connected and (time.time() - start_time) < timeout:
                    time.sleep(0.1)
                
                if self.connected:
                    return True
                else:
                    logger.warning("Connection timeout, trying fallback methods...")
                    self.client.loop_stop()
                    self.client.disconnect()
                    
            except Exception as e:
                logger.warning(f"Primary connection failed: {e}")
                self.client.loop_stop()
                try:
                    self.client.disconnect()
                except:
                    pass
            
            # If primary connection failed, try fallback methods
            if self.use_tls and not self.connected:
                logger.info("Trying TLS fallback methods...")
                
                # Fallback 1: Try completely insecure TLS
                try:
                    self.client.tls_set()
                    self.client.tls_insecure_set(True)
                    
                    self.client.connect(self.broker_host, self.broker_port, 60)
                    self.client.loop_start()
                    
                    timeout = 10
                    start_time = time.time()
                    while not self.connected and (time.time() - start_time) < timeout:
                        time.sleep(0.1)
                    
                    if self.connected:
                        logger.info("✅ Connected using insecure TLS fallback")
                        return True
                        
                    self.client.loop_stop()
                    self.client.disconnect()
                    
                except Exception as e:
                    logger.warning(f"Insecure TLS fallback failed: {e}")
                    try:
                        self.client.loop_stop()
                        self.client.disconnect()
                    except:
                        pass
                
                # Fallback 2: Try non-TLS connection on port 1883
                logger.info("Trying non-TLS connection on port 1883...")
                try:
                    # Create new client without TLS
                    self.client = mqtt.Client(client_id=self.client_id)
                    self.client.on_connect = self.on_connect
                    self.client.on_disconnect = self.on_disconnect
                    self.client.on_message = self.on_message
                    
                    self.client.connect(self.broker_host, 1883, 60)
                    self.client.loop_start()
                    
                    timeout = 10
                    start_time = time.time()
                    while not self.connected and (time.time() - start_time) < timeout:
                        time.sleep(0.1)
                    
                    if self.connected:
                        logger.info("✅ Connected using non-TLS on port 1883")
                        return True
                        
                except Exception as e:
                    logger.warning(f"Non-TLS fallback failed: {e}")
            
            return self.connected
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker"""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info(f"Device {self.device_id} disconnected")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")

    def run(self):
        """Run the Opentrons edge device"""
        if not self.connect():
            logger.error("Failed to connect to MQTT broker")
            return False
        
        # Check robot connection on startup
        logger.info(f"Checking connection to Opentrons robot at {self.robot_ip}...")
        if not self.check_robot_connection():
            logger.warning(f"⚠️ Opentrons robot at {self.robot_ip} is not accessible")
            logger.warning("The edge device will continue running but protocol execution will fail")
        else:
            logger.info(f"✅ Opentrons robot at {self.robot_ip} is accessible")
        
        logger.info(f"Opentrons Edge Device {self.device_id} running...")
        logger.info("Waiting for protocol commands from HPC...")
        
        try:
            last_heartbeat = time.time()
            last_robot_check = time.time()
            
            while True:
                current_time = time.time()
                
                # Send heartbeat every 5 seconds
                if current_time - last_heartbeat >= 5:
                    self.send_heartbeat()
                    last_heartbeat = current_time
                
                # Check robot connection every 60 seconds
                if current_time - last_robot_check >= 60:
                    self.check_robot_connection()
                    last_robot_check = current_time
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Opentrons Edge Device interrupted by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.send_status_update("offline")
            self.disconnect()


def main():
    parser = argparse.ArgumentParser(description='Opentrons Edge Device - Real Opentrons OT-2 robot interface via MQTT')
    parser.add_argument('--broker', default='192.168.50.131', help='MQTT broker hostname (default: 192.168.50.131)')
    parser.add_argument('--port', type=int, default=8883, help='MQTT broker port (default: 8883 for TLS)')
    parser.add_argument('--no-tls', action='store_true', help='Disable TLS (use port 1883)')
    parser.add_argument('--tls-version', default='1.2', help='TLS version (default: 1.2)')
    parser.add_argument('--ca-cert', help='Path to CA certificate file for TLS verification')
    parser.add_argument('--robot-ip', default='192.168.50.64', help='Opentrons robot IP address (default: 192.168.50.64)')
    parser.add_argument('--robot-port', type=int, default=31950, help='Opentrons robot API port (default: 31950)')
    
    args = parser.parse_args()
    
    # Adjust port if TLS is disabled
    port = 1883 if args.no_tls else args.port
    use_tls = not args.no_tls
    
    print(f"Starting Opentrons Edge Device")
    print(f"MQTT Broker: {args.broker}:{port}")
    print(f"TLS: {'Enabled' if use_tls else 'Disabled'}")
    if args.ca_cert:
        print(f"CA Certificate: {args.ca_cert}")
    print(f"Opentrons Robot: {args.robot_ip}:{args.robot_port}")
    
    edge_device = OpentronsEdgeDevice(
        broker_host=args.broker,
        broker_port=port,
        use_tls=use_tls,
        ca_cert_path=args.ca_cert,
        robot_ip=args.robot_ip,
        robot_port=args.robot_port
    )
    
    edge_device.run()


if __name__ == "__main__":
    main()