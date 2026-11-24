"""PUDA wire messages to ClickHouse. No payloads or credentials in logs."""

import calendar
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from puda import e2e


@dataclass(repr=False)
class Config:
    servers: list[str]
    url: str
    user: str
    password: str
    database: str = "puda"
    command_table: str = "command_logs"
    telemetry_table: str = "telemetry"
    encrypted: bool = False
    connect_options: dict = field(default_factory=dict)
    max_ack_pending: int = 4096
    batch_size: int = 1000
    batch_interval: float = 1.0
    timeout: float = 30.0

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.getenv(name, "")
            if not value or any(c in value for c in "\r\n\0"):
                raise ValueError(
                    f"{name} is required and must not contain control characters"
                )
            if name in ("CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD") and any(
                not 32 <= ord(c) <= 126 for c in value
            ):
                raise ValueError(
                    f"{name} must use printable ASCII for HTTP header authentication"
                )
            return value

        def number(name, default, kind, maximum):
            try:
                value = kind(os.getenv(name, str(default)))
                if not 0 < value <= maximum or not math.isfinite(value):
                    raise ValueError
                return value
            except ValueError:
                raise ValueError(
                    f"{name} must be positive and at most {maximum}"
                ) from None

        servers = [s.strip() for s in required("NATS_SERVERS").split(",") if s.strip()]
        ca, key = (
            os.getenv(k, "").strip() for k in ("PUDA_NATS_CA", "PUDA_E2E_KEY_FILE")
        )
        if bool(ca) != bool(key):
            raise ValueError("Set both PUDA_NATS_CA and PUDA_E2E_KEY_FILE, or neither")
        scheme = "tls" if ca else "nats"
        if not servers:
            raise ValueError("NATS_SERVERS is required")
        for server in servers:
            try:
                parsed = urlsplit(server)
                valid = (
                    parsed.scheme == scheme
                    and parsed.hostname
                    and parsed.port
                    and not parsed.query
                    and not parsed.fragment
                    and parsed.path in ("", "/")
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    f"NATS_SERVERS requires valid {scheme}://host:port URLs"
                )
        if ca:
            if not Path(ca).is_file() or not Path(key).is_file():
                raise ValueError("TLS CA and E2EE key files must exist")
            if not os.access(key, os.W_OK) or not os.access(Path(key).parent, os.W_OK):
                raise ValueError(
                    "E2EE key file and directory must be writable for rotation"
                )
            try:
                if e2e.reload() is None:
                    raise ValueError
            except Exception:
                raise ValueError(
                    "E2EE key file must contain a valid encrypt key"
                ) from None
        else:
            e2e.set_ring(None)
        try:
            options = e2e.connect_kwargs(servers)
        except Exception:
            raise ValueError("Cannot load TLS CA") from None
        url = required("CLICKHOUSE_URL").rstrip("/")
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme in ("http", "https")
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and parsed.path == ""
            )
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "CLICKHOUSE_URL must be an http(s) origin without credentials, path, query or fragment"
            )
        if "CLICKHOUSE_TABLE" in os.environ:
            raise ValueError(
                "Replace CLICKHOUSE_TABLE with CLICKHOUSE_COMMAND_TABLE and "
                "CLICKHOUSE_TELEMETRY_TABLE after migration"
            )
        identifiers = {}
        for name, default in (
            ("DATABASE", "puda"),
            ("COMMAND_TABLE", "command_logs"),
            ("TELEMETRY_TABLE", "telemetry"),
        ):
            value = os.getenv("CLICKHOUSE_" + name, default)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
                raise ValueError(f"CLICKHOUSE_{name} must be a SQL identifier")
            identifiers[name.lower()] = value
        if identifiers["command_table"] == identifiers["telemetry_table"]:
            raise ValueError("Command and telemetry tables must differ")
        return cls(
            servers=servers,
            url=url,
            user=required("CLICKHOUSE_USER"),
            password=required("CLICKHOUSE_PASSWORD"),
            encrypted=bool(ca),
            connect_options=options,
            **identifiers,
            max_ack_pending=number("JS_MAX_ACK_PENDING", 4096, int, 100000),
            batch_size=number("BATCH_SIZE", 1000, int, 10000),
            batch_interval=number("BATCH_INTERVAL", 1, float, 5),
            timeout=number("CLICKHOUSE_TIMEOUT", 30, float, 45),
        )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ClickHouse:
    def __init__(self, config):
        self.config = config
        # Never forward database credentials through redirects or environment proxies.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, query, body=b""):
        params = urlencode(dict(query=query, async_insert=0, wait_end_of_query=1))
        request = Request(
            self.config.url + "/?" + params,
            data=body,
            method="POST",
            headers={
                "X-ClickHouse-User": self.config.user,
                "X-ClickHouse-Key": self.config.password,
                "Content-Type": "application/x-ndjson",
            },
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                result = response.read()
                if response.status != 200:
                    raise RuntimeError
                return result
        except Exception:
            # HTTP error bodies and URLs may contain raw data/credentials.
            raise RuntimeError("ClickHouse request failed") from None

    def write(self, rows):
        groups = {self.config.command_table: [], self.config.telemetry_table: []}
        for row in rows:
            kind = row["msg_type"]
            if kind in ("command", "response"):
                groups[self.config.command_table].append(row)
            elif kind in ("telemetry", "telemetry_stream"):
                groups[self.config.telemetry_table].append(row)
            else:
                raise ValueError("Unsupported row type")
        for table, batch in groups.items():
            if batch:
                self._write_table(table, batch)

    def _write_table(self, table, rows):
        body = b"".join(
            (
                json.dumps(
                    row, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                + "\n"
            ).encode("utf-8")
            for row in rows
        )
        result = self.request(
            f"INSERT INTO `{self.config.database}`.`{table}` FORMAT JSONEachRow",
            body,
        )
        # INSERT success has an empty body. Even HTTP 200 can contain late errors.
        if result.strip():
            raise RuntimeError("ClickHouse insert was not confirmed")

    def check(self):
        for table in (self.config.command_table, self.config.telemetry_table):
            if self.request(
                f"SELECT count() FROM `{self.config.database}`.`{table}` WHERE 0"
            ).strip() != b"0":
                raise RuntimeError("ClickHouse schema check failed")


def timestamp_ns(value):
    if value is None:
        return time.time_ns()
    if not isinstance(value, str):
        raise ValueError("timestamp must be RFC3339")
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
        value,
    )
    if not match:
        raise ValueError("timestamp must be RFC3339")
    dt = datetime.fromisoformat(match[1] + match[3].replace("Z", "+00:00"))
    result = calendar.timegm(dt.utctimetuple()) * 1_000_000_000 + int(
        (match[2] or "").ljust(9, "0")
    )
    # DateTime64(9) has a narrower range than other DateTime64 precisions.
    if not 0 <= result < 2**63:
        raise ValueError("timestamp outside supported nanosecond range")
    return result


def to_row(subject, payload):
    def reject_constant(_):
        raise ValueError("non-finite JSON number")

    data = json.loads(payload, parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("payload must be an object")
    # Also reject overflowing JSON numbers (1e999) and invalid UTF-8/surrogates.
    json.dumps(data, allow_nan=False, ensure_ascii=False).encode("utf-8")
    parts = subject.split(".")
    if (
        len(parts) < 4
        or parts[0] != "puda"
        or any(not p or p in ("*", ">") for p in parts)
    ):
        raise ValueError("unsupported subject")
    row = dict(
        subject=subject,
        machine_id=parts[1],
        topic=".".join(parts[3:]),
        msg_type="",
        received_ns=time.time_ns(),
        raw_json=payload.decode("utf-8"),
        event_id=hashlib.sha256(subject.encode() + b"\0" + payload).hexdigest(),
    )
    if parts[2:] == ["tlm", "health"] or (
        len(parts) >= 5 and parts[2:4] == ["tlm", "stream"]
    ):
        row["msg_type"] = "telemetry" if parts[3] == "health" else "telemetry_stream"
        row["stream"] = "health" if parts[3] == "health" else ".".join(parts[4:])
        row["event_ns"] = timestamp_ns(data.get("timestamp"))
        # Exact two-key object envelope only; legacy objects with extra fields
        # (including their own `data` measurement) must not lose those fields.
        if set(data) == {"timestamp", "data"} and isinstance(data["data"], dict):
            values = data["data"]
        else:
            values = {key: value for key, value in data.items() if key != "timestamp"}
        row["data"] = json.dumps(
            values, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        )
        return row
    if parts[2:] not in (
        ["cmd", "queue"],
        ["cmd", "immediate"],
        ["cmd", "response", "queue"],
        ["cmd", "response", "immediate"],
    ):
        raise ValueError("unsupported subject")
    header, command = data["header"], data["command"]
    if not isinstance(header, dict) or not isinstance(command, dict):
        raise ValueError("invalid command")
    for key, source, source_field in (
        ("machine_id", header, "machine_id"),
        ("run_id", header, "run_id"),
        ("username", header, "username"),
        ("user_id", header, "user_id"),
        ("cmd_name", command, "name"),
        ("cmd_version", command, "version"),
    ):
        value = source.get(source_field)
        if value is None and key not in ("machine_id", "cmd_name"):
            value = ""
        if not isinstance(value, str):
            raise ValueError("invalid command string field")
        row[key] = value
    step = command["step_number"]
    if (
        isinstance(step, bool)
        or not isinstance(step, int)
        or not -(2**63) <= step < 2**63
    ):
        raise ValueError("step_number must be int64")
    row["step_number"] = step
    row["event_ns"] = timestamp_ns(header["timestamp"])
    row["msg_type"] = "response" if len(parts) == 5 else "command"
    row["status"] = "sent"
    if row["msg_type"] == "response":
        response = data["response"]
        if not isinstance(response, dict) or not isinstance(
            response.get("status"), str
        ):
            raise ValueError("invalid response")
        row["status"] = response["status"]
    return row
