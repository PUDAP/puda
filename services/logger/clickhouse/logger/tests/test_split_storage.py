"""Storage-only normalization; the SDK/NATS wire format stays unchanged."""
import json

import pytest

from storage import to_row, ClickHouse, Config
from test_http import http_server
from test_logger import command
from urllib.parse import parse_qs, urlsplit


def test_check_requires_both_tables(http_server):
    server, records = http_server
    server.body = b"0\n"
    client = ClickHouse(Config([], f"http://127.0.0.1:{server.server_port}", "test", "fake"))
    client.check()
    queries = [parse_qs(urlsplit(path).query)["query"][0] for path, _, _ in records]
    assert len(queries) == 2
    assert "`command_logs`" in queries[0] and "`telemetry`" in queries[1]
    # A pre-1.0 command table without protocol_version fails the check.
    assert "count(protocol_version)" in queries[0]


def test_mixed_batch_routes_to_separate_tables(http_server):
    server, records = http_server
    client = ClickHouse(Config([], f"http://127.0.0.1:{server.server_port}", "test", "fake"))
    client.write([
        to_row("puda.robot.cmd.queue", json.dumps(command()).encode()),
        to_row("puda.robot.tlm.health", b'{"timestamp": "2026-07-07T09:41:42Z", "data": {"status": "ready"}}'),
        to_row("puda.robot.cmd.response.immediate", json.dumps(command()).encode()),
    ])
    assert len(records) == 2
    tables = {}
    for path, _, body in records:
        sql = parse_qs(urlsplit(path).query)["query"][0]
        tables[sql] = [json.loads(line) for line in body.splitlines()]
    commands = tables["INSERT INTO `puda`.`command_logs` FORMAT JSONEachRow"]
    telemetry = tables["INSERT INTO `puda`.`telemetry` FORMAT JSONEachRow"]
    assert [row["msg_type"] for row in commands] == ["command", "response"]
    assert [(row["user_id"], row["username"]) for row in commands] == [("user-1", "tester")] * 2
    assert [row["protocol_version"] for row in commands] == ["1.0", "1.0"]
    assert not any("cmd_version" in row for row in commands)
    assert not any("stream" in row or "data" in row for row in commands)
    assert len(telemetry) == 1 and json.loads(telemetry[0]["data"]) == {"status": "ready"}


@pytest.mark.parametrize("suffix,kind,stream", [
    ("health", "telemetry", "health"),
    ("stream.position.axes", "telemetry_stream", "position.axes"),
])
def test_telemetry_wrapper_unwraps_data_once(suffix, kind, stream):
    actual = {"timestamp": "measurement time", "data": {"x": [None, 3]}, "status": None,
              "nested": {"values": [1, None, True]}}
    raw = json.dumps({"timestamp": "2026-07-07T11:41:42.123456789+02:00", "data": actual},
                     indent=2).encode()
    row = to_row("puda.robot.tlm." + suffix, raw)
    assert row["stream"] == stream
    assert row["msg_type"] == kind
    assert row["machine_id"] == "robot"
    assert row["event_ns"] == 1783417302123456789
    assert json.loads(row["data"]) == actual
    assert row["raw_json"] == raw.decode()
    assert not {"cpu", "mem", "temp", "run_id", "cmd_name", "status"} & row.keys()


def test_unknown_wrapper_siblings_are_ignored_but_kept_in_raw_json():
    raw = b'{"timestamp":"2026-07-07T09:41:42Z","data":{"x":1},"future":true}'
    row = to_row("puda.robot.tlm.health", raw)
    assert json.loads(row["data"]) == {"x": 1} and row["raw_json"] == raw.decode()


@pytest.mark.parametrize("payload", [
    {"cpu": 1, "status": "ok"},
    {"timestamp": "2026-07-07T09:41:42Z", "cpu": 1},
    {"data": {"x": 1}},
    {"timestamp": None, "data": {"x": 1}},
    {"timestamp": "2026-07-07T09:41:42Z", "data": None},
])
def test_telemetry_without_wrapper_is_invalid(payload):
    with pytest.raises(ValueError):
        to_row("puda.robot.tlm.health", json.dumps(payload).encode())
