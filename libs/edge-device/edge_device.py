#!/usr/bin/env python3
"""
Base Edge Device
Abstract base class for edge devices that communicate via NATS.io
Provides common functionality for device registration, messaging, and status updates
"""

import json
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import nats
from nats.aio.client import Client as NATS
import asyncio

# Configure logging
logger = logging.getLogger(__name__)


class EdgeDevice(ABC):
    """
    Abstract base class for edge devices
    Handles NATS connection, message routing, status updates, and heartbeat
    """

    def __init__(
        self,
        device_id: str,
        device_type: str,
        device_name: str,
        nats_servers: list = None,
        capabilities: list = None,
        connection_info: Dict[str, Any] = None,
    ):
        """
        Initialize edge device

        Args:
            device_id: Unique device identifier
            device_type: Type of device (e.g., "opentrons", "thermocycler")
            device_name: Human-readable device name
            nats_servers: List of NATS server URLs (default: ["nats://localhost:4222"])
            capabilities: List of device capabilities
            connection_info: Additional connection information
        """
        self.device_id = device_id
        self.device_type = device_type
        self.device_name = device_name
        self.nats_servers = nats_servers or ["nats://localhost:4222"]
        self.capabilities = capabilities or []
        self.connection_info = connection_info or {}

        # NATS client
        self.nc: Optional[NATS] = None

        # Device state
        self.connected = False
        self.processing = False
        self.current_task_id = None

        # Subjects (NATS topics)
        self.protocol_subject = f"lab.{self.device_id}.protocols"
        self.cancel_subject = f"lab.{self.device_id}.cancel"
        self.response_subject = f"lab.{self.device_id}.response"
        self.status_subject = f"lab.{self.device_id}.status"
        self.heartbeat_subject = f"lab.{self.device_id}.heartbeat"
        self.task_complete_subject = f"lab.{self.device_id}.task_complete"
        self.task_failed_subject = f"lab.{self.device_id}.task_failed"

        # Message handlers
        self.message_handlers: Dict[str, Callable] = {
            self.protocol_subject: self.handle_protocol_message,
            self.cancel_subject: self.handle_cancel_message,
        }

        # Subscriptions
        self.subscriptions = []

    async def connect(self) -> bool:
        """Connect to NATS server"""
        try:
            logger.info(
                f"Device {self.device_id} connecting to NATS servers: {self.nats_servers}"
            )

            # Connect to NATS
            self.nc = await nats.connect(servers=self.nats_servers)

            self.connected = True
            logger.info(f"Device {self.device_id} connected to NATS")

            # Subscribe to subjects
            await self._subscribe_all()

            # Send initial status and heartbeat
            await self.send_status_update("online")
            await self.send_heartbeat()

            return True

        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            self.connected = False
            return False

    async def _subscribe_all(self):
        """Subscribe to all message subjects"""
        for subject, handler in self.message_handlers.items():
            try:
                sub = await self.nc.subscribe(subject, cb=self._create_handler(handler))
                self.subscriptions.append(sub)
                logger.info(f"Subscribed to {subject}")
            except Exception as e:
                logger.error(f"Failed to subscribe to {subject}: {e}")

    def _create_handler(self, handler: Callable):
        """Create async message handler wrapper"""

        async def message_handler(msg):
            try:
                payload = json.loads(msg.data.decode())
                logger.info(f"Received message on {msg.subject}: {payload}")
                await handler(payload)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON message: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")

        return message_handler

    async def disconnect(self):
        """Disconnect from NATS server"""
        try:
            # Unsubscribe from all subjects
            for sub in self.subscriptions:
                try:
                    await sub.unsubscribe()
                except Exception as e:
                    logger.warning(f"Error unsubscribing: {e}")

            # Close connection
            if self.nc:
                await self.nc.close()

            self.connected = False
            self.subscriptions = []
            logger.info(f"Device {self.device_id} disconnected from NATS")

        except Exception as e:
            logger.error(f"Error during disconnect: {e}")

    async def publish(self, subject: str, data: Dict[str, Any]):
        """Publish message to NATS subject"""
        try:
            if not self.nc or not self.connected:
                logger.warning("Not connected to NATS, cannot publish")
                return

            message = json.dumps(data)
            await self.nc.publish(subject, message.encode())
            logger.debug(f"Published to {subject}")

        except Exception as e:
            logger.error(f"Error publishing to {subject}: {e}")

    async def handle_protocol_message(self, payload: Dict[str, Any]):
        """Handle protocol/task execution messages - to be implemented by subclasses"""
        try:
            task_id = payload.get("task_id") or payload.get("protocol_id")
            task_data = payload.get("task_data") or payload.get("protocol_data", {})

            logger.info(f"Executing task {task_id}")

            # Update device status
            self.processing = True
            self.current_task_id = task_id
            await self.send_status_update("busy")

            # Validate task
            validation_result = await self.validate_task(task_data)
            if not validation_result.get("valid", False):
                errors = validation_result.get("errors", [])
                await self.send_task_failed(task_id, errors)
                self.processing = False
                self.current_task_id = None
                await self.send_status_update("online")
                return

            # Execute task in background
            asyncio.create_task(self.execute_task_async(task_id, task_data))

        except Exception as e:
            logger.error(f"Error handling protocol message: {e}")
            task_id = payload.get("task_id") or payload.get("protocol_id")
            await self.send_task_failed(task_id, str(e))
            self.processing = False
            self.current_task_id = None
            await self.send_status_update("online")

    async def handle_cancel_message(self, payload: Dict[str, Any]):
        """Handle task cancellation messages"""
        try:
            task_id = payload.get("task_id") or payload.get("protocol_id")
            logger.info(f"Cancelling task {task_id}")

            # Cancel the task (to be implemented by subclasses)
            await self.cancel_task(task_id)

            # Update device status
            self.processing = False
            self.current_task_id = None
            await self.send_status_update("online")

            # Send cancellation response
            response = {
                "task_id": task_id,
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
                "status": "cancelled",
                "message": f"Task {task_id} cancelled by {self.device_id}",
            }

            await self.publish(self.response_subject, response)
            logger.info(f"Sent cancellation response for {task_id}")

        except Exception as e:
            logger.error(f"Error handling cancel message: {e}")

    async def send_status_update(self, status: str):
        """Send status update with comprehensive device information"""
        try:
            device_status = await self.get_device_status()
            message = {
                "device_id": self.device_id,
                "device_type": self.device_type,
                "device_name": self.device_name,
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "processing": self.processing,
                "current_task_id": self.current_task_id,
                "capabilities": self.capabilities,
                "connection_info": self.connection_info,
                "device_status": device_status,
            }

            await self.publish(self.status_subject, message)
            logger.info(f"Sent status update: {status}")

        except Exception as e:
            logger.error(f"Error sending status update: {e}")

    async def send_heartbeat(self):
        """Send heartbeat message"""
        try:
            device_status = await self.get_device_status()
            message = {
                "device_id": self.device_id,
                "device_type": self.device_type,
                "device_name": self.device_name,
                "status": "online",
                "timestamp": datetime.now().isoformat(),
                "processing": self.processing,
                "current_task_id": self.current_task_id,
                "capabilities": self.capabilities,
                "connection_info": self.connection_info,
                "device_status": device_status,
            }

            await self.publish(self.heartbeat_subject, message)
            logger.debug("Sent heartbeat")

        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")

    async def send_task_complete(self, task_id: str, results: Dict[str, Any]):
        """Send task completion message"""
        try:
            message = {
                "task_id": task_id,
                "device_id": self.device_id,
                "device_type": self.device_type,
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "results": results,
            }

            await self.publish(self.task_complete_subject, message)
            logger.info(f"Sent task completion for {task_id}")

        except Exception as e:
            logger.error(f"Error sending task completion: {e}")

    async def send_task_failed(self, task_id: str, error: Any):
        """Send task failure message"""
        try:
            error_msg = error
            if isinstance(error, list):
                error_msg = "; ".join(str(e) for e in error)
            elif not isinstance(error, str):
                error_msg = str(error)

            message = {
                "task_id": task_id,
                "device_id": self.device_id,
                "device_type": self.device_type,
                "status": "failed",
                "timestamp": datetime.now().isoformat(),
                "error": error_msg,
            }

            await self.publish(self.task_failed_subject, message)
            logger.error(f"Sent task failure for {task_id}: {error_msg}")

        except Exception as e:
            logger.error(f"Error sending task failure: {e}")

    async def run(self):
        """Run the edge device - main event loop"""
        if not await self.connect():
            logger.error("Failed to connect to NATS server")
            return False

        # Perform initial device checks
        logger.info("Performing initial device checks...")
        await self.initialize_device()

        logger.info(f"Edge Device {self.device_id} running...")
        logger.info("Waiting for task commands...")

        try:
            last_heartbeat = time.time()
            last_device_check = time.time()

            # Keep connection alive and send periodic updates
            while True:
                current_time = time.time()

                # Send heartbeat every 5 seconds
                if current_time - last_heartbeat >= 5:
                    await self.send_heartbeat()
                    last_heartbeat = current_time

                # Perform device checks every 60 seconds
                if current_time - last_device_check >= 60:
                    await self.check_device_connection()
                    last_device_check = current_time

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Edge Device interrupted by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.send_status_update("offline")
            await self.disconnect()

    # Abstract methods to be implemented by subclasses

    @abstractmethod
    async def validate_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate task data before execution

        Returns:
            Dict with 'valid' (bool) and 'errors' (list) keys
        """
        pass

    @abstractmethod
    async def execute_task_async(self, task_id: str, task_data: Dict[str, Any]):
        """
        Execute task asynchronously
        Should call send_task_complete() or send_task_failed() when done
        """
        pass

    @abstractmethod
    async def cancel_task(self, task_id: str):
        """Cancel a running task"""
        pass

    @abstractmethod
    async def get_device_status(self) -> Dict[str, Any]:
        """Get current device status information"""
        pass

    @abstractmethod
    async def check_device_connection(self) -> bool:
        """Check if device is accessible/connected"""
        pass

    @abstractmethod
    async def initialize_device(self):
        """Initialize device on startup"""
        pass


