"""SDK telemetry envelope compatibility at the existing Influx boundary."""
import json
import pytest
from subscriber import to_line
from test_subscriber import stream_data


def test_new_health_envelope_keeps_existing_numeric_fields():
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42.123456789Z", "data": {"cpu": 6, "mem": None, "status": "ok"}}).encode()
    line = to_line("puda.first.tlm.health", raw)
    assert "cpu=6.0" in line and "status=ok" in line
    assert line.endswith(" 1783417302123456789")


def test_new_stream_envelope_unwraps_once():
    actual = {"data": {"custom": [1, None]}, "timestamp": "sensor time", "status": None}
    line = to_line("puda.first.tlm.stream.position", json.dumps({"timestamp": "2026-07-07T09:41:42Z", "data": actual}).encode())
    assert stream_data(line) == actual
    assert line.endswith(" 1783417302000000000")


def test_legacy_data_measurement_with_siblings_is_not_unwrapped():
    original = {"timestamp": "2026-07-07T09:41:42Z", "data": {"x": None}, "status": "ok"}
    line = to_line("puda.first.tlm.stream.position", json.dumps(original).encode())
    assert stream_data(line) == original
