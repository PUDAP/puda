import json
import pytest


def command():
    return {
        "header": {
            "machine_id": "robot",
            "run_id": "run-1",
            "username": "tester",
            "user_id": "user-1",
            "timestamp": "2026-07-07T09:41:42.123456789Z",
        },
        "command": {
            "name": "move",
            "step_number": 2,
            "version": "1.0",
            "params": {"x": 3},
        },
        "response": {"status": "success", "data": {"x": 3}},
    }


def test_command_keeps_raw_json_and_nanoseconds():
    from subscriber import to_row

    raw = json.dumps(command(), indent=2).encode()
    row = to_row("puda.robot.cmd.response.queue", raw)
    assert row["raw_json"] == raw.decode()
    assert row["event_ns"] == 1783417302123456789
    assert (row["machine_id"], row["run_id"], row["cmd_name"], row["step_number"]) == (
        "robot",
        "run-1",
        "move",
        2,
    )
    assert row["msg_type"] == "response"
    assert row["status"] == "success"


@pytest.mark.parametrize(
    "subject,payload",
    [
        ("puda.robot.tlm.health", b"[]"),
        ("puda.robot.tlm.health", b'{"cpu":NaN}'),
        ("puda.robot.tlm.health", b'{"cpu":1e999}'),
        ("puda.robot.tlm.health", b"\xff"),
        ("puda.robot.cmd.queue", b"{}"),
        ("puda.robot.cmd.other", b"{}"),
    ],
)
def test_invalid_messages_rejected(subject, payload):
    from subscriber import to_row

    with pytest.raises((ValueError, KeyError, UnicodeError)):
        to_row(subject, payload)


def test_health_and_stream_without_timestamp_use_receipt_time():
    import time
    from subscriber import to_row, timestamp_ns

    before = time.time_ns()
    row = to_row("puda.robot.tlm.health", b'{"cpu":4.5,"mem":null}')
    assert before <= row["event_ns"] <= time.time_ns()
    assert json.loads(row["data"]) == {"cpu": 4.5, "mem": None}
    row = to_row("puda.robot.tlm.stream.position", b'{"x":1}')
    assert row["stream"] == "position" and row["msg_type"] == "telemetry_stream"
    assert timestamp_ns("2026-07-07T11:41:42.123456789+02:00") == 1783417302123456789
    with pytest.raises(ValueError):
        timestamp_ns("2026-07-07T11:41:42+01:99")


def env(monkeypatch):
    import os

    for key in list(os.environ):
        if key.startswith(("CLICKHOUSE_", "NATS_", "PUDA_", "JS_", "BATCH_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("NATS_SERVERS", "nats://127.0.0.1:14222")
    monkeypatch.setenv("CLICKHOUSE_URL", "http://127.0.0.1:18123")
    monkeypatch.setenv("CLICKHOUSE_USER", "test")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "test-secret")


def test_config_requires_credentials_and_validates_identifiers(monkeypatch):
    from subscriber import Config

    env(monkeypatch)
    config = Config.from_env()
    assert config.database == "puda"
    assert config.command_table == "command_logs" and config.telemetry_table == "telemetry"
    for name in ("CLICKHOUSE_COMMAND_TABLE", "CLICKHOUSE_TELEMETRY_TABLE"):
        with monkeypatch.context() as local:
            local.setenv(name, "bad;sql")
            with pytest.raises(ValueError):
                Config.from_env()
    with monkeypatch.context() as local:
        local.setenv("CLICKHOUSE_TABLE", "events")
        with pytest.raises(ValueError, match="CLICKHOUSE_TABLE"):
            Config.from_env()
    with monkeypatch.context() as local:
        local.setenv("CLICKHOUSE_COMMAND_TABLE", "same")
        local.setenv("CLICKHOUSE_TELEMETRY_TABLE", "same")
        with pytest.raises(ValueError):
            Config.from_env()
    for key, value in [
        ("CLICKHOUSE_PASSWORD", ""),
        ("CLICKHOUSE_DATABASE", "puda; DROP TABLE events"),
        ("CLICKHOUSE_URL", "http://user:secret@localhost:8123"),
        ("CLICKHOUSE_URL", "http://localhost:8123/?password=secret"),
        ("NATS_SERVERS", "https://localhost:4222"),
        ("JS_MAX_ACK_PENDING", "0"),
        ("BATCH_SIZE", "0"),
        ("CLICKHOUSE_TIMEOUT", "nan"),
        ("PUDA_NATS_CA", "/missing"),
        ("CLICKHOUSE_PASSWORD", "secret-☃"),
        ("CLICKHOUSE_USER", "test\x01"),
        ("CLICKHOUSE_URL", "http://@localhost:8123"),
    ]:
        with monkeypatch.context() as local:
            local.setenv(key, value)
            with pytest.raises(ValueError):
                Config.from_env()
