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


def test_legacy_export_conversion_preserves_receipt_and_duplicate_rows():
    from backfill import convert
    legacy = to_row("puda.robot.tlm.health", b'{"status":"ok","x":[null,1]}')
    legacy.pop("data")
    legacy["stream"] = ""
    legacy["event_ns"], legacy["received_ns"] = 123456789, 987654321
    rows = list(convert([legacy, legacy]))
    assert len(rows) == 2
    for table, row in rows:
        assert table == "telemetry"
        assert row["event_ns"] == 123456789 and row["received_ns"] == 987654321
        assert row["event_id"] == legacy["event_id"]
        assert row["stream"] == "health"
        assert json.loads(row["data"]) == {"status": "ok", "x": [None, 1]}
        assert row["raw_json"] == legacy["raw_json"]


def test_backfill_cli_produces_offline_files_without_connections(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    source = tmp_path / "legacy.jsonl"
    row = to_row("puda.robot.cmd.queue", json.dumps(command()).encode())
    source.write_text(json.dumps(row) + "\n")
    output = tmp_path / "converted"
    script = Path(__file__).resolve().parents[1] / "backfill.py"
    result = subprocess.run([sys.executable, str(script), str(source), str(output)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads((output / "command_logs.jsonl").read_text()) == row
    assert (output / "telemetry.jsonl").read_text() == ""
    again = subprocess.run([sys.executable, str(script), str(source), str(output)], capture_output=True)
    assert again.returncode != 0  # Refuse accidental reuse/overwrite.


def test_mixed_batch_routes_to_separate_tables(http_server):
    server, records = http_server
    client = ClickHouse(Config([], f"http://127.0.0.1:{server.server_port}", "test", "fake"))
    client.write([
        to_row("puda.robot.cmd.queue", json.dumps(command()).encode()),
        to_row("puda.robot.tlm.health", b'{"status": "ready"}'),
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
    assert [(row["user_id"], row["username"], row["cmd_version"]) for row in commands] == [("user-1", "tester", "1.0")] * 2
    assert not any("stream" in row or "data" in row for row in commands)
    assert len(telemetry) == 1 and json.loads(telemetry[0]["data"]) == {"status": "ready"}


@pytest.mark.parametrize("suffix,kind,stream", [
    ("health", "telemetry", "health"),
    ("stream.position.axes", "telemetry_stream", "position.axes"),
])
def test_telemetry_preserves_generic_data_without_timestamp(suffix, kind, stream):
    payload = {"timestamp": "2026-07-07T11:41:42.123456789+02:00",
               "cpu": None, "status": "ready", "nested": {"values": [1, None, True]},
               "data": {"custom": "not an envelope"}, "temperature": {"sensor": 21}}
    raw = json.dumps(payload, indent=2).encode()
    row = to_row("puda.robot.tlm." + suffix, raw)
    assert row["stream"] == stream
    assert row["msg_type"] == kind
    assert row["machine_id"] == "robot"
    assert row["event_ns"] == 1783417302123456789
    assert json.loads(row["data"]) == {k: v for k, v in payload.items() if k != "timestamp"}
    assert row["raw_json"] == raw.decode()
    assert not {"cpu", "mem", "temp", "run_id", "cmd_name", "status"} & row.keys()


@pytest.mark.parametrize("suffix", ["health", "stream.position"])
def test_new_exact_envelope_unwraps_once(suffix):
    actual = {"timestamp": "measurement time", "data": {"x": [None, 3]}, "status": None}
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42Z", "data": actual}).encode()
    row = to_row("puda.robot.tlm." + suffix, raw)
    assert json.loads(row["data"]) == actual
    assert row["raw_json"] == raw.decode()


@pytest.mark.parametrize("payload", [{"data": {"x": 1}}, {"timestamp": None, "data": None}])
def test_legacy_data_key_without_exact_object_envelope_is_preserved(payload):
    row = to_row("puda.robot.tlm.health", json.dumps(payload).encode())
    assert json.loads(row["data"]) == {k: v for k, v in payload.items() if k != "timestamp"}
