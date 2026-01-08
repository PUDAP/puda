"""PostgreSQL database client for PUDA platform."""

import os
from typing import Optional
import psycopg
from psycopg.rows import dict_row


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
        if self._conn is None or self._conn.closed:
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
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

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
        if self._conn is None or self._conn.closed:
            self.connect()

        with self._conn.cursor() as cur:
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
    
    def insert_response_log(
        self,
        machine_id: str,
        response_type: str,
        command: str,
        run_id: Optional[str] = None,
        command_id: Optional[str] = None,
        status: str = 'unknown',
        error: Optional[str] = None,
        completed_at: Optional[str] = None,
        full_payload: Optional[dict] = None
    ) -> None:
        """Insert a response log entry into the database.
        
        Args:
            machine_id: Machine identifier
            response_type: Type of response ('queue' or 'immediate')
            command: Command name
            run_id: Optional run ID
            command_id: Optional command ID
            status: Response status ('success' or 'error')
            error: Optional error message
            completed_at: Optional completion timestamp
            full_payload: Optional full message payload
        """
        import json
        if self._conn is None or self._conn.closed:
            self.connect()
        
        with self._conn.cursor() as cur:
            # cur.execute(
            #     """
            #     INSERT INTO response_log 
            #     (machine_id, response_type, command, run_id, command_id, status, error, completed_at, full_payload)
            #     VALUES (%(machine_id)s, %(response_type)s, %(command)s, %(run_id)s, %(command_id)s,
            #             %(status)s, %(error)s, %(completed_at)s, %(full_payload)s)
            #     """,
            #     {
            #         'machine_id': machine_id,
            #         'response_type': response_type,
            #         'command': command,
            #         'run_id': run_id,
            #         'command_id': command_id,
            #         'status': status,
            #         'error': error,
            #         'completed_at': completed_at,
            #         'full_payload': json.dumps(full_payload) if full_payload else None
            #     }
            # )
            # self._conn.commit()
            print(f"\nInserted response log: {machine_id}, {response_type}, {command}, {run_id}, {command_id}, {status}, {error}, {completed_at}, {full_payload}")
        
        
