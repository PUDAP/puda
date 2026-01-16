"""
Configuration utilities for the First Machine MCP Server.

Centralized configuration management.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file in current working directory
# For Docker: env vars are already loaded by docker-compose
# For local dev: looks for .env in the directory where the script is run from
load_dotenv()


class Config:
    """Configuration class for MCP server settings."""
    
    # MCP Server
    MACHINE_ID: str = os.getenv('MACHINE_ID', 'first')
    KV_BUCKET_NAME: str = f"MACHINE_STATE_{MACHINE_ID.replace('.', '-')}"
    
    # Server metadata
    SERVER_NAME: str = f"{MACHINE_ID.capitalize()}MCP"
    SERVER_VERSION: str = os.getenv('SERVER_VERSION', '0.1.0')
    SERVER_PORT: int = int(os.getenv('SERVER_PORT', '8001'))
    
    # NATS servers configuration
    DEFAULT_NATS_SERVERS = (
        'nats://192.168.50.201:4222,'
        'nats://192.168.50.201:4223,'
        'nats://192.168.50.201:4224'
    )
    NATS_SERVERS_ENV: str = os.getenv('NATS_SERVERS', DEFAULT_NATS_SERVERS)
    NATS_SERVERS: list = [s.strip() for s in NATS_SERVERS_ENV.split(',')]