"""Protocol 1.0 §12: telemetry always uses the {timestamp, data} wrapper."""
import json
import pytest
from subscriber import to_line
from test_subscriber import stream_data


def test_health_envelope_keeps_numeric_fields():
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42.123456789Z", "data": {"cpu": 6, "mem": None, "status": "ok"}}).encode()
    line = to_line("puda.first.tlm.health", raw)
    assert "cpu=6.0" in line and "status=ok" in line
    assert line.endswith(" 1783417302123456789")


def test_stream_envelope_unwraps_once():
    actual = {"data": {"custom": [1, None]}, "timestamp": "sensor time", "status": None}
    line = to_line("puda.first.tlm.stream.position", json.dumps({"timestamp": "2026-07-07T09:41:42Z", "data": actual}).encode())
    assert stream_data(line) == actual
    assert line.endswith(" 1783417302000000000")


def test_unknown_wrapper_fields_ignored():
    raw = {"timestamp": "2026-07-07T09:41:42Z", "data": {"x": 1}, "extra": True}
    line = to_line("puda.first.tlm.stream.pos", json.dumps(raw).encode())
    assert stream_data(line) == {"x": 1}


@pytest.mark.parametrize("subject", ["puda.first.tlm.health", "puda.first.tlm.stream.pos"])
@pytest.mark.parametrize(
    "payload",
    [
        {"timestamp": "2026-07-07T09:41:42Z", "cpu": 6.0},  # legacy flattened
        {"cpu": 6.0},
        {"data": {"cpu": 6.0}},  # missing timestamp
        {"timestamp": None, "data": {"cpu": 6.0}},
        {"timestamp": "yesterday", "data": {"cpu": 6.0}},
        {"timestamp": "2026-07-07T09:41:42Z", "data": [6.0]},
        {"timestamp": "2026-07-07T09:41:42Z", "data": None},
    ],
)
def test_unwrapped_or_invalid_telemetry_rejected(subject, payload):
    with pytest.raises(ValueError):
        to_line(subject, json.dumps(payload).encode())
