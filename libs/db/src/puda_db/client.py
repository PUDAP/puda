"""PostgreSQL database client for PUDA platform."""

import os
import logging
from typing import Optional
import psycopg
from psycopg.rows import dict_row
from puda.models import NATSMessage


logger = logging.getLogger(__name__)

class DatabaseClient:
    """Client for interacting with PostgreSQL database."""

    def __init__(
        self,
        host: str,
        port: int = 5432,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize database client.

        Args:
            host: Database host
            port: Database port (default: 5432)
            database: Database name (defaults to POSTGRES_DB env var, or "puda" if not set)
            user: Database user (defaults to POSTGRES_USER env var, or "puda" if not set)
            password: Database password (defaults to POSTGRES_PASSWORD env var, or None if not set)
        """
        self.host = host
        self.port = port
        self.database = database or os.getenv("POSTGRES_DB", "puda")
        self.user = user or os.getenv("POSTGRES_USER", "puda")
        self.password = password or os.getenv("POSTGRES_PASSWORD")
        self._conn: Optional[psycopg.Connection] = None

    def connect(self) -> None:
        """Establish connection to the database."""
        if self._conn is None or getattr(self._conn, 'closed', False):
            self._conn = psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
                row_factory=dict_row,
            )

    def close(self) -> None:
        """Close the database connection."""
        logger.info("Closing database connection")
        if self._conn is not None and not getattr(self._conn, 'closed', False):
            self._conn.close()  # type: ignore[attr-defined]  # pylint: disable=no-member
            self._conn = None
            logger.info("Closed database connection")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def query(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """Execute a SQL query and return results.

        Args:
            sql: SQL query statement
            params: Optional query parameters as a dictionary

        Returns:
            List of result rows as dictionaries
        """
        logger.info("Executing SQL query: %s", sql)
        if self._conn is None:
            self.connect()
        elif getattr(self._conn, 'closed', False):
            self.connect()
        
        conn = self._conn
        if conn is None:
            raise RuntimeError("Failed to establish database connection")
        
        with conn.cursor() as cur:  # type: ignore[attr-defined]  # pylint: disable=no-member
            cur.execute(sql, params)
            return cur.fetchall()


    def insert_measurement(self, measurement: dict) -> None:
        """Insert a measurement into the database."""
        self.query(
            "INSERT INTO measurements (measurement_id, measurement_name, measurement_value) VALUES (%(measurement_id)s, %(measurement_name)s, %(measurement_value)s)",
            measurement
        )

    def insert_sample(self, sample: dict) -> None:
        """Insert a sample into the database."""
        self.query(
            "INSERT INTO samples (sample_id, sample_name, sample_value) VALUES (%(sample_id)s, %(sample_name)s, %(sample_value)s)",
            sample
        )
    
    def insert_command_log(self, message: NATSMessage, command_type: str) -> None:
        """Insert a command log entry into the database.
        
        Args:
            message: NATSMessage to store in the database
            command_type: Type of command being logged
        """
        if self._conn is None:
            self.connect()
        elif getattr(self._conn, 'closed', False):
            self.connect()

        if self._conn is None or getattr(self._conn, 'closed', False):
            raise RuntimeError("Failed to establish database connection")
        
        # Extract fields from NATSMessage
        run_id = message.header.run_id
        machine_id = message.header.machine_id
        created_at = message.header.timestamp
        step_number = message.command.step_number if message.command else None
        payload = message.model_dump_json()
        
        conn = self._conn
        if conn is None:
            raise RuntimeError("Failed to establish database connection")
        
        with conn.cursor() as cur:  # type: ignore[attr-defined]  # pylint: disable=no-member
            cur.execute(
                """
                INSERT INTO command_log (run_id, created_at, step_number, payload, machine_id, command_type)
                VALUES (%(run_id)s, %(created_at)s, %(step_number)s, %(payload)s::jsonb, %(machine_id)s, %(command_type)s)
                """,
                {
                    'run_id': run_id,
                    'machine_id': machine_id,
                    'command_type': command_type,
                    'created_at': created_at,
                    'step_number': step_number,
                    'payload': payload
                }
            )
        conn.commit()  # type: ignore[attr-defined]  # pylint: disable=no-member
        logger.info("Inserted command log entry into the database")
        
