import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nats.js.api import RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError
from puda import e2e

from e2e_context import ring_context
from subscriber import Config, Subscriber, timestamp_ns, to_line


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "NATS_SERVERS",
        "PUDA_NATS_CA",
        "PUDA_E2E_KEY_FILE",
        "JS_MAX_ACK_PENDING",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def command():
    return {
        "header": {
            "protocol_version": "1.0",
            "machine_id": "first",
            "timestamp": "2026-07-07T09:41:42Z",
            "username": "user",
            "run_id": "run-1",
            "user_id": "user-1",
        },
        "command": {"name": "home", "step_number": 1},
        "response": {
            "status": "success",
            "code": 200,
            "message": 'done "ok"',
            "completed_at": "2026-07-07T09:41:43Z",
        },
    }


def test_plaintext_config(monkeypatch):
    monkeypatch.setenv("NATS_SERVERS", " nats://one:4222, ,nats://two:4222 ")
    monkeypatch.setenv("PUDA_NATS_CA", " ")
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", "")
    config = Config.from_env()
    assert not config.encrypted
    assert config.servers == ["nats://one:4222", "nats://two:4222"]
    assert config.connect_options == {}
    assert not config.context.enabled()


@pytest.mark.parametrize("variable", ["PUDA_NATS_CA", "PUDA_E2E_KEY_FILE"])
def test_partial_config_rejected(monkeypatch, variable):
    monkeypatch.setenv("NATS_SERVERS", "nats://one:4222")
    monkeypatch.setenv(variable, "/missing")
    with pytest.raises(ValueError, match="Set both"):
        Config.from_env()


@pytest.mark.parametrize(
    "servers", ["", "tls://one:4222", "nats://one:4222,tls://two:4222"]
)
def test_plaintext_invalid_servers(monkeypatch, servers):
    monkeypatch.setenv("NATS_SERVERS", servers)
    with pytest.raises(ValueError):
        Config.from_env()


@pytest.mark.parametrize(
    "key_text", ["", "encrypt=not-a-key", "encrypt=TOP_SECRET_BAD_KEY"]
)
def test_bad_key_rejected_without_leak(monkeypatch, tmp_path, key_text):
    ca, key = tmp_path / "ca.pem", tmp_path / "e2e.key"
    ca.write_text("placeholder")
    key.write_text(key_text)
    monkeypatch.setenv("NATS_SERVERS", "tls://localhost:4222")
    monkeypatch.setenv("PUDA_NATS_CA", str(ca))
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", str(key))
    with pytest.raises(ValueError, match="valid encrypt key") as error:
        Config.from_env()
    assert "TOP_SECRET" not in str(error.value)


def test_e2ee_config_requires_files_and_tls(monkeypatch, tmp_path):
    monkeypatch.setenv("NATS_SERVERS", "tls://localhost:4222")
    monkeypatch.setenv("PUDA_NATS_CA", str(tmp_path / "missing"))
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", str(tmp_path / "missing-key"))
    with pytest.raises(ValueError, match="existing files"):
        Config.from_env()
    monkeypatch.setenv("NATS_SERVERS", "nats://localhost:4222")
    with pytest.raises(ValueError, match="tls://"):
        Config.from_env()


def test_e2ee_valid_key_bad_ca(monkeypatch, tmp_path):
    ca, key = tmp_path / "ca.pem", tmp_path / "e2e.key"
    ca.write_text("invalid certificate")
    key.write_text("encrypt=" + base64.b64encode(b"a" * 32).decode())
    monkeypatch.setenv("NATS_SERVERS", "tls://localhost:4222")
    monkeypatch.setenv("PUDA_NATS_CA", str(ca))
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", str(key))
    with pytest.raises(ValueError, match="TLS CA"):
        Config.from_env()


def test_command_schema(command):
    line = to_line("puda.first.cmd.queue", json.dumps(command).encode())
    assert line == (
        "commands,cmd_name=home,machine_id=first,msg_type=command,"
        "protocol_version=1.0,run_id=run-1,status=sent,subject=puda.first.cmd.queue,"
        "topic=queue,username=user "
        'step_number=1i,user_id="user-1" 1783417302000000000'
    )


def test_response_schema(command):
    line = to_line("puda.first.cmd.response.immediate", json.dumps(command).encode())
    assert "msg_type=response" in line
    assert "topic=response.immediate" in line
    assert 'response_code="200"' in line
    assert 'response_message="done \\"ok\\""' in line
    assert "status=success" in line


def tlm(data, timestamp="2026-07-07T09:41:42.123456789Z"):
    return json.dumps({"timestamp": timestamp, "data": data}).encode()


def test_health_scalars_and_nanosecond_time():
    line = to_line("puda.first.tlm.health", tlm({"cpu": 6.0}))
    assert line.startswith(
        "telemetry,machine_id=first,subject=puda.first.tlm.health cpu=6.0 "
    )
    assert "data=" not in line
    assert line.endswith("1783417302123456789")
    assert timestamp_ns("2026-07-07T17:41:42.123456789+08:00") == 1783417302123456789


def test_escaping_and_null_fields(command):
    command["command"]["name"] = "move = x,y"
    command["header"]["username"] = "ACME\\user"
    command["response"]["message"] = "line1\nline2\\end"
    command["response"]["code"] = None
    line = to_line("puda.first.cmd.response.queue", json.dumps(command).encode())
    assert "cmd_name=move\\ \\=\\ x\\,y" in line
    assert "\n" not in line
    assert "response_code=" not in line
    assert "username=ACME\\\\user " in line


@pytest.mark.parametrize("value", [None, ""])
def test_optional_command_context_tags(command, value):
    command["header"]["run_id"] = value
    command["header"]["username"] = value
    line = to_line("puda.first.cmd.queue", json.dumps(command).encode())
    assert "run_id=" not in line
    assert "username=" not in line


def test_command_context_tag_escaping(command):
    command["header"]["run_id"] = "run = 1,2"
    command["header"]["username"] = "test user"
    line = to_line("puda.first.cmd.queue", json.dumps(command).encode())
    assert "run_id=run\\ \\=\\ 1\\,2" in line
    assert "username=test\\ user " in line


def test_health_scalars_status_and_fallback():
    line = to_line(
        "puda.first.tlm.health",
        tlm({"cpu": 2, "mem": 4, "temp": None, "connected": True, "status": "ok"}),
    )
    assert "cpu=2.0,mem=4.0" in line
    assert "connected=" not in line
    assert "status=ok" in line
    assert "temp=" not in line
    assert "data=" in to_line("puda.first.tlm.health", tlm({"custom": 42}))


def stream_data(line):
    fields = line.split(" ", 1)[1].rsplit(" ", 1)[0]
    assert fields.startswith("data=")
    return json.loads(json.loads(fields.removeprefix("data=")))


@pytest.mark.parametrize("connected", [True, False])
def test_connected_is_only_preserved_in_json(connected):
    health = to_line("puda.first.tlm.health", tlm({"connected": connected}))
    assert "connected=" not in health
    assert stream_data(health)["data"] == {"connected": connected}
    stream = to_line("puda.first.tlm.stream.device", tlm({"connected": connected}))
    assert stream_data(stream) == {"connected": connected}


def test_driver_stream_json():
    payload = {
        "x": 1,
        "y": 2.5,
        "ready": True,
        "unit": "mm",
        "missing": None,
        "axes": [1, 2],
        "meta": {"mode": "xyz"},
        "mass g,raw=": 3,
        "label": 'quoted "text"\nnext\\line µ',
    }
    line = to_line("puda.first.tlm.stream.pos", tlm(payload))
    assert line.startswith("telemetry_stream,machine_id=first,stream=pos,")
    assert stream_data(line) == payload
    assert "\n" not in line
    assert line.endswith("1783417302123456789")


@pytest.mark.parametrize(
    "payload", [{}, {"x": None}, {"": 1}, {"machine_id": "bad"}, {"bad\nname": 1}]
)
def test_driver_stream_arbitrary_objects(payload):
    line = to_line("puda.first.tlm.stream.pos", tlm(payload))
    assert stream_data(line) == payload


@pytest.mark.parametrize("value", [1, "one", True, None, [1], {"x": 1}])
def test_driver_stream_mixed_value_types(value):
    for stream in ("pos", "weight"):
        line = to_line(f"puda.first.tlm.stream.{stream}", tlm({"value": value}))
        assert stream_data(line) == {"value": value}


@pytest.mark.parametrize(
    "payload",
    [
        b'{"timestamp":"2026-07-07T09:41:42Z","data":{"x":NaN}}',
        b'{"timestamp":"2026-07-07T09:41:42Z","data":{"x":[Infinity]}}',
        b"[]",
        b"null",
        b"not json",
    ],
)
def test_invalid_driver_stream_payload(payload):
    with pytest.raises(ValueError):
        to_line("puda.first.tlm.stream.pos", payload)


def test_response_data_fallback(command):
    command["response"]["message"] = ""
    command["response"]["data"] = {"result": 42}
    line = to_line("puda.first.cmd.response.queue", json.dumps(command).encode())
    assert 'response_message="{\\"result\\":42}"' in line
    assert "response_data=" not in line


@pytest.mark.parametrize("payload", [b"[]", b"{}", b"not json"])
def test_malformed_messages(payload):
    with pytest.raises((ValueError, KeyError)):
        to_line("puda.first.cmd.queue", payload)


def message(payload):
    return SimpleNamespace(
        subject="puda.first.cmd.response.queue",
        data=payload,
        ack=AsyncMock(),
        nak=AsyncMock(),
        term=AsyncMock(),
    )


async def test_plaintext_and_e2ee_identical_output(command):
    subscriber = Subscriber(Config([], False, {}))
    subscriber.emit = Mock()
    payload = json.dumps(command).encode()
    await subscriber.process(message(payload), True)
    plain_line = subscriber.emit.call_args.args[0]
    subscriber.config.context = ring_context(e2e.Ring(encrypt=b"a" * 32))
    encrypted = message(
        subscriber.config.context.seal("puda.first.cmd.response.queue", payload)
    )
    await subscriber.process(encrypted, True)
    assert subscriber.emit.call_args.args[0] == plain_line
    encrypted.ack.assert_awaited_once()


async def test_ack_only_after_stdout(command):
    subscriber = Subscriber(Config([], False, {}))
    msg = message(json.dumps(command).encode())

    def emit(line):
        msg.ack.assert_not_awaited()

    subscriber.emit = emit
    await subscriber.process(msg, True)
    msg.ack.assert_awaited_once()
    subscriber.emit = Mock(side_effect=BrokenPipeError)
    msg.ack.reset_mock()
    with pytest.raises(BrokenPipeError):
        await subscriber.process(msg, True)
    msg.ack.assert_not_awaited()


async def test_core_messages_never_acked(command):
    subscriber = Subscriber(Config([], False, {}))
    subscriber.emit = Mock()
    msg = message(json.dumps(command).encode())
    await subscriber.process(msg)
    msg.ack.assert_not_awaited()


async def test_wrong_key_retries_without_emitting(command):
    sender = ring_context(e2e.Ring(encrypt=b"a" * 32))
    msg = message(
        sender.seal("puda.first.cmd.response.queue", json.dumps(command).encode())
    )
    wrong = ring_context(e2e.Ring(encrypt=b"b" * 32))
    subscriber = Subscriber(Config([], True, {}, context=wrong))
    subscriber.sync_keyring = AsyncMock()
    subscriber.emit = Mock()
    await subscriber.process(msg, True)
    subscriber.emit.assert_not_called()
    subscriber.sync_keyring.assert_awaited_once()
    msg.nak.assert_awaited_once_with(delay=5)
    msg.ack.assert_not_awaited()


async def test_plaintext_rejected_when_encrypted(command):
    context = ring_context(e2e.Ring(encrypt=b"a" * 32))
    subscriber = Subscriber(Config([], True, {}, context=context))
    subscriber.sync_keyring = AsyncMock()
    subscriber.emit = Mock()
    msg = message(json.dumps(command).encode())
    await subscriber.process(msg, True)
    subscriber.emit.assert_not_called()
    msg.nak.assert_awaited_once()


async def test_invalid_json_terminated():
    subscriber = Subscriber(Config([], False, {}))
    msg = message(b"invalid")
    await subscriber.process(msg, True)
    msg.term.assert_awaited_once()
    msg.ack.assert_not_awaited()


@pytest.mark.parametrize("version", ["1.0", "1.7", "2.0"])
def test_protocol_version_tag(command, version):
    command["header"]["protocol_version"] = version
    line = to_line("puda.first.cmd.response.queue", json.dumps(command).encode())
    assert f"protocol_version={version}," in line


@pytest.mark.parametrize("version", ["", "1", "v1.0", "1.0.0", 1.0])
def test_protocol_version_invalid(command, version):
    command["header"]["protocol_version"] = version
    with pytest.raises(ValueError):
        to_line("puda.first.cmd.queue", json.dumps(command).encode())


def test_protocol_version_missing_is_logged_without_tag(command):
    """An edge's reply to a malformed command echoes it without protocol_version."""
    del command["header"]["protocol_version"]
    line = to_line("puda.first.cmd.response.queue", json.dumps(command).encode())
    assert line.startswith("commands,") and "protocol_version=" not in line


def test_no_command_or_header_version(command):
    command["header"]["version"] = "0.0.1"
    command["command"]["version"] = "2"
    line = to_line("puda.first.cmd.queue", json.dumps(command).encode())
    assert "cmd_version" not in line and "version=0.0.1" not in line
    assert "version=\"2\"" not in line


@pytest.mark.parametrize(
    "subject",
    ["puda.first.cmd.immediate", "puda.first.cmd.ping", "puda.first.update",
     "puda.first.update.response", "puda.first.tlm.heartbeat"],
)
def test_untapped_subjects_rejected(command, subject):
    with pytest.raises(ValueError):
        to_line(subject, json.dumps(command).encode())


def test_config_has_no_response_max_age(monkeypatch):
    monkeypatch.setenv("NATS_SERVERS", "nats://one:4222")
    monkeypatch.setenv("JS_RESPONSE_MAX_AGE", "not-a-duration")
    config = Config.from_env()
    assert not hasattr(config, "response_max_age")


def stream_info(retention=RetentionPolicy.INTEREST, subject=None, **overrides):
    def info(name):
        config = StreamConfig(
            name=name,
            subjects=[subject or f"puda.*.cmd.response.{name.split('_')[1].lower()}"],
            retention=retention,
            storage=StorageType.FILE,
            max_age=86400.0,
            **overrides,
        )
        return SimpleNamespace(config=config)

    return AsyncMock(side_effect=info)


def stream_subscriber(stream_info_mock):
    subscriber = Subscriber(Config([], False, {}))
    subscriber.js = Mock(
        stream_info=stream_info_mock,
        add_stream=AsyncMock(),
        update_stream=AsyncMock(),
        delete_stream=AsyncMock(),
        consumer_info=AsyncMock(side_effect=NotFoundError),
        add_consumer=AsyncMock(),
    )
    return subscriber


async def test_provisioned_streams_left_unchanged():
    subscriber = stream_subscriber(stream_info())
    await subscriber.ensure_streams()
    subscriber.js.add_stream.assert_not_awaited()
    subscriber.js.update_stream.assert_not_called()
    subscriber.js.delete_stream.assert_not_called()
    assert subscriber.js.add_consumer.await_count == 2


async def test_missing_streams_created_with_spec_settings(caplog):
    subscriber = stream_subscriber(AsyncMock(side_effect=NotFoundError))
    await subscriber.ensure_streams()
    configs = {
        call.kwargs["config"].name: call.kwargs["config"]
        for call in subscriber.js.add_stream.await_args_list
    }
    assert set(configs) == {"RESPONSE_QUEUE", "RESPONSE_IMMEDIATE"}
    for name, config in configs.items():
        assert config.subjects == [f"puda.*.cmd.response.{name[9:].lower()}"]
        assert config.retention == RetentionPolicy.INTEREST
        assert config.storage == StorageType.FILE
        assert config.max_age == 86400
    assert "unprovisioned" in caplog.text
    subscriber.js.update_stream.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"retention": RetentionPolicy.LIMITS},
        {"retention": RetentionPolicy.INTEREST, "storage": StorageType.MEMORY},
        {"retention": RetentionPolicy.INTEREST, "max_age": 3600.0},
    ],
)
async def test_mismatched_stream_logged_not_updated(caplog, overrides):
    retention = overrides.pop("retention")
    info = stream_info(retention)

    async def changed(name):
        result = await info(name)
        for key, value in overrides.items():
            setattr(result.config, key, value)
        return result

    subscriber = stream_subscriber(AsyncMock(side_effect=changed))
    await subscriber.ensure_streams()
    assert "leaving it unchanged" in caplog.text
    subscriber.js.add_stream.assert_not_awaited()
    subscriber.js.update_stream.assert_not_called()
    assert subscriber.js.add_consumer.await_count == 2


async def test_workqueue_stream_refused():
    subscriber = stream_subscriber(stream_info(RetentionPolicy.WORK_QUEUE))
    with pytest.raises(ValueError, match="workqueue"):
        await subscriber.ensure_streams()
    subscriber.js.update_stream.assert_not_called()
    subscriber.js.add_consumer.assert_not_awaited()


async def test_stream_without_expected_subject_refused():
    subscriber = stream_subscriber(stream_info(subject="puda.other"))
    with pytest.raises(ValueError, match="expected response subject"):
        await subscriber.ensure_streams()
    subscriber.js.update_stream.assert_not_called()


def test_no_stream_mutation_in_source():
    source = (Path(__file__).resolve().parents[1] / "subscriber.py").read_text()
    for name in ("update_stream", "delete_stream", "JS_RESPONSE_MAX_AGE",
                 "cmd.immediate\"", "cmd.ping", "cmd_version"):
        assert name not in source
    for script in ("nats-init.sh", "healthcheck.sh", "docker-entrypoint.sh",
                   ".env.example", "compose.yml"):
        text = (Path(__file__).resolve().parents[1] / script).read_text()
        assert "JS_RESPONSE_MAX_AGE" not in text and "nats stream" not in text


async def test_legacy_telemetry_logged_and_dropped(caplog):
    subscriber = Subscriber(Config([], False, {}))
    subscriber.emit = Mock()
    msg = message(b'{"timestamp":"2026-07-07T09:41:42Z","cpu":6.0}')
    msg.subject = "puda.first.tlm.health"
    await subscriber.process(msg)
    subscriber.emit.assert_not_called()
    assert "Invalid message on puda.first.tlm.health" in caplog.text
    msg.ack.assert_not_awaited()
    msg.term.assert_not_awaited()
