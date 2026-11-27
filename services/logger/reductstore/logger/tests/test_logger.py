"""Unit tests: no dotenv, live credentials, broker or database (mocked clients)."""
import base64
import datetime as dt
import importlib
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.errors import NotFoundError
from puda import e2e

with patch("dotenv.load_dotenv", return_value=False):
    main = importlib.import_module("main")


def plain_config(**kw):
    return main.Config(servers=["nats://127.0.0.1:14222"], encrypted=False, connect_options={}, **kw)


def make_service(config=None):
    service = main.LoggerService(config or plain_config())
    service.db = SimpleNamespace(write=AsyncMock())
    return service


def js_msg(subject, data, reply="$JS.ACK.RESPONSE_QUEUE.c.1.1.1.1.0"):
    return SimpleNamespace(
        subject=subject, data=data, reply=reply,
        ack=AsyncMock(), nak=AsyncMock(), term=AsyncMock(),
    )


def core_msg(subject, data):
    return js_msg(subject, data, reply="")


def envelope(response=None, **header):
    body = {
        "header": {
            "protocol_version": "1.0",
            "message_type": "response" if response else "command",
            "user_id": "u-1",
            "username": "puda",
            "machine_id": "first",
            "run_id": "r-1",
            "timestamp": "2026-11-23T13:25:24Z",
            **header,
        },
        "command": {"name": "echo", "params": {"message": "hi"}, "step_number": 3, "machine_id": "first"},
    }
    if response is not None:
        body["response"] = response
    return json.dumps(body).encode()


# --- subjects -----------------------------------------------------------------


async def test_subscribes_only_observer_subjects():
    service = make_service()
    service.nc = MagicMock()
    service.nc.subscribe = AsyncMock()
    service.js = MagicMock()
    service.js.subscribe = AsyncMock()
    service.js.subscribe_bind = AsyncMock()
    service.ensure_consumer = AsyncMock(return_value=ConsumerConfig(durable_name="x"))
    await service._subscribe()

    core = [c.args[0] for c in service.nc.subscribe.await_args_list]
    assert core == ["puda.*.cmd.queue", "puda.*.tlm.health", "puda.*.tlm.stream.>"]
    for subject in core:
        assert "immediate" not in subject and "ping" not in subject and "update" not in subject
        assert subject != "puda.*.cmd.*" and subject != "puda.>"
    # JetStream binds explicitly; never an implicit js.subscribe.
    service.js.subscribe.assert_not_awaited()
    bound = {c.kwargs["stream"]: c.kwargs["consumer"] for c in service.js.subscribe_bind.await_args_list}
    assert bound == {
        "RESPONSE_QUEUE": "reductstore_logger_resp_queue",
        "RESPONSE_IMMEDIATE": "reductstore_logger_resp_immediate",
    }
    assert all(c.kwargs["manual_ack"] for c in service.js.subscribe_bind.await_args_list)


# --- command / response mapping -------------------------------------------------


async def test_queued_command_mapping_and_protocol_version():
    service = make_service()
    raw = envelope()
    msg = core_msg("puda.first.cmd.queue", raw)
    await service._on_command_request(msg)
    entry, stored, timestamp, labels = service.db.write.await_args.args
    assert entry == "commands" and stored == raw
    assert timestamp == dt.datetime(2026, 11, 23, 13, 25, 24, tzinfo=dt.timezone.utc)
    assert labels["protocol_version"] == "1.0"
    assert labels["topic"] == "queue" and labels["msg_type"] == "command"
    assert labels["status"] == "sent" and labels["cmd_name"] == "echo"
    assert labels["step_number"] == 3 and labels["machine_id"] == "first"
    assert "version" not in labels
    msg.ack.assert_not_awaited()  # core message, never acked


async def test_immediate_response_mapping_and_ack():
    service = make_service()
    raw = envelope(response={"status": "error", "completed_at": "2026-11-23T13:25:26Z",
                             "code": "EXECUTION_ERROR", "message": "bad, input", "data": None})
    msg = js_msg("puda.first.cmd.response.immediate", raw)
    await service._on_response(msg)
    _, _, _, labels = service.db.write.await_args.args
    assert labels["topic"] == "response.immediate" and labels["msg_type"] == "response"
    assert labels["status"] == "error" and labels["response_code"] == "EXECUTION_ERROR"
    assert labels["response"] == "bad; input" and labels["protocol_version"] == "1.0"
    msg.ack.assert_awaited_once()


async def test_response_data_label_when_no_message():
    _, labels = main.command_labels(
        "puda.first.cmd.response.queue",
        json.loads(envelope(response={"status": "success", "code": None, "message": None, "data": {"a": 1}})),
        "response",
    )
    assert labels["response"] == '{"a":1}'


@pytest.mark.parametrize("raw", [
    b"not json",
    json.dumps({"data": {"header": {}, "command": {}}}).encode(),  # legacy wrapper
    json.dumps({"header": {"machine_id": "first"}}).encode(),
    json.dumps(["x"]).encode(),
])
async def test_invalid_envelope_is_dropped_and_terminated(raw):
    service = make_service()
    msg = js_msg("puda.first.cmd.response.queue", raw)
    await service._on_response(msg)
    service.db.write.assert_not_awaited()
    msg.term.assert_awaited_once()
    msg.ack.assert_not_awaited()


async def test_store_failure_naks_for_redelivery():
    service = make_service()
    service.db.write.side_effect = RuntimeError("reductstore down")
    msg = js_msg("puda.first.cmd.response.queue", envelope(response={"status": "success"}))
    await service._on_response(msg)
    msg.nak.assert_awaited_once()


async def test_finish_never_replies_to_core_messages():
    service = make_service()
    msg = SimpleNamespace(reply="_INBOX.cli.1", ack=AsyncMock(), nak=AsyncMock(), term=AsyncMock())
    for action in ("ack", "nak", "term"):
        await service._finish(msg, action)
    msg.ack.assert_not_awaited(); msg.nak.assert_not_awaited(); msg.term.assert_not_awaited()


# --- telemetry -------------------------------------------------------------------


async def test_health_uses_wrapper():
    service = make_service()
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42Z", "data": {"cpu": 6, "mem": 40, "temp": None}}).encode()
    await service._on_telemetry(core_msg("puda.first.tlm.health", raw))
    entry, stored, timestamp, labels = service.db.write.await_args.args
    assert entry == "telemetry" and stored == raw
    assert timestamp.isoformat() == "2026-07-07T09:41:42+00:00"
    assert labels == {"machine_id": "first", "subject": "puda.first.tlm.health", "cpu": 6, "mem": 40}


async def test_telemetry_stream_entry_per_machine_and_stream():
    service = make_service()
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42.123456789Z", "data": {"x": 1.5}}).encode()
    await service._on_telemetry_stream(core_msg("puda.esp32-pump-1.tlm.stream.pos", raw))
    entry, stored, timestamp, labels = service.db.write.await_args.args
    assert entry == "stream__esp32-pump-1__pos" and stored == raw
    assert timestamp.microsecond == 123456
    assert labels == {"machine_id": "esp32-pump-1", "stream": "pos", "subject": "puda.esp32-pump-1.tlm.stream.pos"}


@pytest.mark.parametrize("subject,payload", [
    ("puda.first.tlm.health", {"cpu": 5, "mem": 1, "timestamp": "2026-07-07T09:41:42Z"}),  # legacy flat
    ("puda.first.tlm.health", {"timestamp": "2026-07-07T09:41:42Z", "data": 5}),
    ("puda.first.tlm.health", {"data": {"cpu": 1}}),
    ("puda.first.tlm.stream.pos", {"x": 1}),
    ("puda.first.tlm.stream.a.b", {"timestamp": "2026-07-07T09:41:42Z", "data": {}}),
])
async def test_telemetry_without_wrapper_is_dropped(subject, payload):
    service = make_service()
    handler = service._on_telemetry if subject.endswith("health") else service._on_telemetry_stream
    await handler(core_msg(subject, json.dumps(payload).encode()))
    service.db.write.assert_not_awaited()


# --- stream checks ------------------------------------------------------------------


def stream_info(retention=RetentionPolicy.INTEREST, max_age=86400.0, storage=StorageType.FILE, subjects=None):
    return lambda name: SimpleNamespace(config=StreamConfig(
        name=name, subjects=subjects or [main.RESPONSE_STREAMS[name]],
        retention=retention, storage=storage, max_age=max_age,
    ))


def js_mock(info):
    js = MagicMock()
    js.stream_info = AsyncMock(side_effect=info)
    js.add_stream = AsyncMock()
    js.update_stream = AsyncMock()
    js.delete_stream = AsyncMock()
    return js


async def test_existing_streams_are_never_modified(caplog):
    service = make_service()
    service.js = js_mock(stream_info(max_age=0.0, storage=StorageType.MEMORY))
    service.ensure_consumer = AsyncMock()
    await service.ensure_streams()
    service.js.add_stream.assert_not_awaited()
    service.js.update_stream.assert_not_awaited()
    service.js.delete_stream.assert_not_awaited()
    assert "leaving it unchanged" in caplog.text
    assert service.ensure_consumer.await_count == 2


async def test_missing_stream_created_with_spec_settings(caplog):
    service = make_service()
    def missing(name):
        raise NotFoundError()
    service.js = js_mock(missing)
    service.ensure_consumer = AsyncMock()
    await service.ensure_streams()
    configs = {c.kwargs["config"].name: c.kwargs["config"] for c in service.js.add_stream.await_args_list}
    assert set(configs) == {"RESPONSE_QUEUE", "RESPONSE_IMMEDIATE"}
    for name, cfg in configs.items():
        assert cfg.subjects == [main.RESPONSE_STREAMS[name]]
        assert cfg.retention == RetentionPolicy.INTEREST and cfg.storage == StorageType.FILE
        assert cfg.max_age == 86400
    assert "unprovisioned" in caplog.text
    service.js.update_stream.assert_not_awaited()


async def test_workqueue_stream_is_refused():
    service = make_service()
    service.js = js_mock(stream_info(retention=RetentionPolicy.WORK_QUEUE))
    service.ensure_consumer = AsyncMock()
    with pytest.raises(ValueError, match="workqueue"):
        await service.ensure_streams()
    service.js.update_stream.assert_not_awaited()


async def test_durable_consumer_created_when_missing():
    service = make_service()
    service.js = MagicMock()
    service.js.consumer_info = AsyncMock(side_effect=NotFoundError())
    service.js.add_consumer = AsyncMock(side_effect=lambda stream, config: SimpleNamespace(config=config))
    config = await service.ensure_consumer("RESPONSE_QUEUE", "puda.*.cmd.response.queue")
    assert config.durable_name == config.deliver_group == "reductstore_logger_resp_queue"
    assert config.filter_subject == "puda.*.cmd.response.queue"
    assert config.ack_policy == AckPolicy.EXPLICIT and config.deliver_subject


async def test_incompatible_consumer_is_an_error():
    service = make_service()
    service.js = MagicMock()
    service.js.consumer_info = AsyncMock(return_value=SimpleNamespace(config=ConsumerConfig(
        durable_name="reductstore_logger_resp_queue", filter_subject="puda.>", ack_policy=AckPolicy.EXPLICIT)))
    service.js.add_consumer = AsyncMock()
    with pytest.raises(ValueError, match="Incompatible"):
        await service.ensure_consumer("RESPONSE_QUEUE", "puda.*.cmd.response.queue")
    service.js.add_consumer.assert_not_awaited()


# --- E2E config -----------------------------------------------------------------------


def write_ca(path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(1)
        .not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


@pytest.fixture
def keyed_env(tmp_path, monkeypatch):
    ca, key = tmp_path / "ca.pem", tmp_path / "e2e.key"
    write_ca(ca)
    key.write_text("encrypt=" + base64.b64encode(os.urandom(32)).decode() + "\n")
    key.chmod(0o600)
    monkeypatch.setenv("NATS_SERVERS", "tls://127.0.0.1:14222,tls://127.0.0.1:14223")
    monkeypatch.setenv("PUDA_NATS_CA", str(ca))
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", str(key))
    return key


def test_plaintext_config_when_both_unset(monkeypatch):
    monkeypatch.setenv("NATS_SERVERS", "nats://a:4222, nats://b:4222")
    monkeypatch.delenv("PUDA_NATS_CA", raising=False)
    monkeypatch.delenv("PUDA_E2E_KEY_FILE", raising=False)
    config = main.Config.from_env()
    assert config.servers == ["nats://a:4222", "nats://b:4222"]
    assert not config.encrypted and not config.context.enabled() and config.connect_options == {}


def test_e2e_config(keyed_env):
    config = main.Config.from_env()
    assert config.encrypted and config.context.enabled()
    assert "tls" in config.connect_options


@pytest.mark.parametrize("env", [
    {"NATS_SERVERS": "nats://a:4222", "PUDA_NATS_CA": "/tmp/ca.pem"},
    {"NATS_SERVERS": "nats://a:4222", "PUDA_E2E_KEY_FILE": "/tmp/e2e.key"},
    {"NATS_SERVERS": "tls://a:4222"},
    {"NATS_SERVERS": ""},
])
def test_config_errors(monkeypatch, env):
    for name in ("NATS_SERVERS", "PUDA_NATS_CA", "PUDA_E2E_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        main.Config.from_env()


def test_keyed_config_rejects_nats_scheme(keyed_env, monkeypatch):
    monkeypatch.setenv("NATS_SERVERS", "tls://a:4222,nats://b:4222")
    with pytest.raises(ValueError, match="tls://"):
        main.Config.from_env()


async def test_e2e_opens_sealed_and_refuses_plaintext(keyed_env):
    config = main.Config.from_env()
    service = make_service(config)
    service.sync_keyring = AsyncMock()
    subject = "puda.first.cmd.response.queue"
    plain = envelope(response={"status": "success"})
    sealed = e2e.Context(str(keyed_env)).seal(subject, plain)

    msg = js_msg(subject, sealed)
    await service._on_response(msg)
    entry, stored, _, labels = service.db.write.await_args.args
    assert stored == plain and labels["protocol_version"] == "1.0"
    msg.ack.assert_awaited_once()

    service.db.write.reset_mock()
    msg = js_msg(subject, plain)
    await service._on_response(msg)
    service.db.write.assert_not_awaited()
    msg.term.assert_awaited_once()


async def test_plaintext_mode_rejects_sealed_frames(keyed_env):
    service = make_service()
    subject = "puda.first.tlm.health"
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42Z", "data": {"cpu": 1}}).encode()
    await service._on_telemetry(core_msg(subject, e2e.Context(str(keyed_env)).seal(subject, raw)))
    service.db.write.assert_not_awaited()
