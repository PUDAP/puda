"""Unit tests for the postgres logger (no live NATS or PostgreSQL)."""

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from nats.js.api import AckPolicy, RetentionPolicy
from nats.js.errors import NotFoundError
from puda import e2e
from puda.models import NATSMessage

import main
from db_client import DatabaseClient
from main import LoggerService, NatsConfig

INIT_SQL = Path(__file__).resolve().parents[2] / "server" / "init.sql"
SUBJECT = "puda.m1.cmd.response.queue"


def response(protocol_version="1.0", **header):
    body = {
        "header": {
            "message_type": "response",
            "user_id": "u1",
            "username": "puda",
            "machine_id": "m1",
            "run_id": "r1",
            "timestamp": "2026-11-23T13:25:26Z",
            **header,
        },
        "command": {"name": "echo", "params": {"message": "hi"}, "step_number": 3, "machine_id": "m1"},
        "response": {"status": "success", "completed_at": "2026-11-23T13:25:26Z", "data": {"message": "hi"}},
    }
    if protocol_version is not None:
        body["header"]["protocol_version"] = protocol_version
    return json.dumps(body).encode()


def fake_msg(data, subject=SUBJECT):
    return SimpleNamespace(subject=subject, data=data, ack=AsyncMock(), nak=AsyncMock(), term=AsyncMock())


def key_file(tmp_path, name="e2e.key"):
    path = tmp_path / name
    path.write_text("encrypt=" + base64.b64encode(os.urandom(32)).decode() + "\n")
    path.chmod(0o600)
    return path


def service(key=None, ca=None, servers=("nats://localhost:4222",)):
    return LoggerService(NatsConfig(list(servers), ca, key), db_client=MagicMock())


# ---------------- E2E / NATS config ----------------

@pytest.fixture
def env(monkeypatch):
    for var in ("NATS_SERVERS", "PUDA_NATS_CA", "PUDA_E2E_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_plaintext_when_both_unset(env):
    env.setenv("NATS_SERVERS", "nats://a:4222, nats://b:4222")
    cfg = NatsConfig.from_env()
    assert cfg.servers == ["nats://a:4222", "nats://b:4222"]
    assert not cfg.encrypted and cfg.ca_file is None


def test_e2e_when_both_set(env, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    key = key_file(tmp_path)
    env.setenv("NATS_SERVERS", "tls://a:4222")
    env.setenv("PUDA_NATS_CA", str(ca))
    env.setenv("PUDA_E2E_KEY_FILE", str(key))
    cfg = NatsConfig.from_env()
    assert cfg.encrypted and cfg.ca_file == str(ca) and cfg.e2e_key_file == str(key)


@pytest.mark.parametrize("var", ["PUDA_NATS_CA", "PUDA_E2E_KEY_FILE"])
def test_only_one_variable_is_startup_error(env, tmp_path, var):
    env.setenv("NATS_SERVERS", "tls://a:4222")
    env.setenv(var, str(key_file(tmp_path)))
    with pytest.raises(ValueError, match="both"):
        NatsConfig.from_env()


def test_plaintext_rejects_tls_urls(env):
    env.setenv("NATS_SERVERS", "nats://a:4222,tls://b:4222")
    with pytest.raises(ValueError, match="nats://"):
        NatsConfig.from_env()


def test_e2e_rejects_nats_urls(env, tmp_path):
    env.setenv("NATS_SERVERS", "nats://a:4222")
    env.setenv("PUDA_NATS_CA", str(key_file(tmp_path, "ca.pem")))
    env.setenv("PUDA_E2E_KEY_FILE", str(key_file(tmp_path)))
    with pytest.raises(ValueError, match="tls://"):
        NatsConfig.from_env()


def test_e2e_rejects_missing_or_invalid_files(env, tmp_path):
    env.setenv("NATS_SERVERS", "tls://a:4222")
    env.setenv("PUDA_NATS_CA", str(tmp_path / "missing.pem"))
    env.setenv("PUDA_E2E_KEY_FILE", str(key_file(tmp_path)))
    with pytest.raises(ValueError, match="existing files"):
        NatsConfig.from_env()
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    bad = tmp_path / "bad.key"
    bad.write_text("nonsense\n")
    env.setenv("PUDA_NATS_CA", str(ca))
    env.setenv("PUDA_E2E_KEY_FILE", str(bad))
    with pytest.raises(ValueError, match="valid encrypt key"):
        NatsConfig.from_env()


def test_missing_servers(env):
    with pytest.raises(ValueError, match="NATS_SERVERS"):
        NatsConfig.from_env()


# ---------------- Message handling ----------------

async def test_valid_response_is_stored_and_acked():
    svc = service()
    msg = fake_msg(response())
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    svc.db_client.insert_command_log.assert_called_once()
    kwargs = svc.db_client.insert_command_log.call_args.kwargs
    assert kwargs["command_type"] == "queue"
    assert kwargs["message"].header.protocol_version == "1.0"
    msg.ack.assert_awaited_once()
    msg.nak.assert_not_awaited()


async def test_immediate_stream_maps_to_immediate():
    svc = service()
    msg = fake_msg(response(), "puda.m1.cmd.response.immediate")
    await svc.handle_message(msg, "RESPONSE_IMMEDIATE", main.RESPONSE_IMMEDIATE_PATTERN)
    assert svc.db_client.insert_command_log.call_args.kwargs["command_type"] == "immediate"
    msg.ack.assert_awaited_once()


@pytest.mark.parametrize("version", [None, "0.9", "2.0", "1"])
async def test_missing_or_unsupported_protocol_version_is_terminated(version):
    svc = service()
    msg = fake_msg(response(protocol_version=version))
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    svc.db_client.insert_command_log.assert_not_called()
    msg.term.assert_awaited_once()
    msg.ack.assert_not_awaited()


async def test_minor_version_accepted():
    svc = service()
    msg = fake_msg(response(protocol_version="1.3"))
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    msg.ack.assert_awaited_once()


async def test_garbage_is_terminated():
    svc = service()
    msg = fake_msg(b"not json")
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    msg.term.assert_awaited_once()


async def test_database_failure_naks_for_redelivery():
    svc = service()
    svc.db_client.insert_command_log.side_effect = RuntimeError("db down")
    msg = fake_msg(response())
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()


async def test_e2e_sealed_payload_is_opened(tmp_path):
    key = key_file(tmp_path)
    svc = service(key=str(key), ca=None)
    sealed = e2e.Context(str(key)).seal(SUBJECT, response())
    msg = fake_msg(sealed)
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    assert svc.db_client.insert_command_log.call_args.kwargs["message"].command.name == "echo"
    msg.ack.assert_awaited_once()


async def test_e2e_refuses_plaintext_when_keyed(tmp_path):
    svc = service(key=str(key_file(tmp_path)))
    svc.js = MagicMock()
    svc.js.key_value = AsyncMock(side_effect=NotFoundError)
    msg = fake_msg(response())
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    svc.db_client.insert_command_log.assert_not_called()
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()


async def test_plaintext_refuses_sealed_payload(tmp_path):
    svc = service()
    sealed = e2e.Context(str(key_file(tmp_path))).seal(SUBJECT, response())
    msg = fake_msg(sealed)
    await svc.handle_message(msg, "RESPONSE_QUEUE", main.RESPONSE_QUEUE_PATTERN)
    svc.db_client.insert_command_log.assert_not_called()
    msg.nak.assert_awaited_once()


# ---------------- Database mapping ----------------

def test_insert_command_log_maps_protocol_version_and_fields():
    client = DatabaseClient(host="localhost", database="puda", user="u", password="p")
    cursor = MagicMock()
    conn = MagicMock(closed=False)
    conn.cursor.return_value.__enter__.return_value = cursor
    client._conn = conn
    message = NATSMessage.model_validate_json(response())
    client.insert_command_log(message=message, command_type="queue")
    sql, params = cursor.execute.call_args.args
    assert "protocol_version" in sql
    assert params["protocol_version"] == "1.0"
    assert params["command_name"] == "echo"
    assert params["step_number"] == 3
    assert params["run_id"] == "r1" and params["machine_id"] == "m1"
    assert params["created_at"] == "2026-11-23T13:25:26Z"
    assert params["command_type"] == "queue"
    assert json.loads(params["payload"])["header"]["protocol_version"] == "1.0"
    assert not any(k in params for k in ("version", "command_version", "header_version"))
    conn.commit.assert_called_once()


def test_init_sql_has_protocol_version_and_no_legacy_version_columns():
    sql = INIT_SQL.read_text()
    assert "protocol_version TEXT NOT NULL" in sql
    for line in sql.splitlines():
        token = line.strip().split(" ")[0]
        assert token in ("", "protocol_version") or "version" not in token


# ---------------- Streams and subscriptions ----------------

def stream_info(subject, retention=RetentionPolicy.INTEREST):
    return SimpleNamespace(config=SimpleNamespace(subjects=[subject], retention=retention))


def mock_js(streams):
    js = MagicMock()
    async def info(name):
        if name not in streams:
            raise NotFoundError
        return streams[name]
    js.stream_info = AsyncMock(side_effect=info)
    js.add_stream = AsyncMock()
    js.update_stream = AsyncMock()
    js.delete_stream = AsyncMock()
    js.delete_consumer = AsyncMock()
    return js


def assert_streams_untouched(js):
    js.add_stream.assert_not_called()
    js.update_stream.assert_not_called()
    js.delete_stream.assert_not_called()
    js.delete_consumer.assert_not_called()


async def test_check_streams_ok_uses_stream_info_only():
    svc = service()
    svc.js = mock_js({s: stream_info(sub) for s, (sub, _, _) in main.SUBSCRIPTIONS.items()})
    await svc.check_streams()
    assert svc.js.stream_info.await_count == 2
    assert_streams_untouched(svc.js)


async def test_check_streams_missing_stream_is_error_not_created():
    svc = service()
    svc.js = mock_js({"RESPONSE_QUEUE": stream_info(main.RESPONSE_QUEUE_PATTERN)})
    with pytest.raises(RuntimeError, match="RESPONSE_IMMEDIATE"):
        await svc.check_streams()
    assert_streams_untouched(svc.js)


async def test_check_streams_wrong_subject_is_error():
    svc = service()
    svc.js = mock_js({
        "RESPONSE_QUEUE": stream_info("puda.*.cmd.queue"),
        "RESPONSE_IMMEDIATE": stream_info(main.RESPONSE_IMMEDIATE_PATTERN),
    })
    with pytest.raises(RuntimeError, match="subject"):
        await svc.check_streams()


async def test_check_streams_retention_mismatch_is_logged_and_left(caplog):
    svc = service()
    svc.js = mock_js({
        s: stream_info(sub, RetentionPolicy.LIMITS) for s, (sub, _, _) in main.SUBSCRIPTIONS.items()
    })
    await svc.check_streams()
    assert "expected interest" in caplog.text
    assert_streams_untouched(svc.js)


async def test_subscribe_creates_durable_with_manual_ack():
    svc = service()
    svc.js = mock_js({})
    svc.js.consumer_info = AsyncMock(side_effect=NotFoundError)
    svc.js.subscribe = AsyncMock(return_value=MagicMock())
    for stream in main.SUBSCRIPTIONS:
        await svc.subscribe_stream(stream)
    calls = svc.js.subscribe.await_args_list
    assert [c.args[0] for c in calls] == [main.RESPONSE_QUEUE_PATTERN, main.RESPONSE_IMMEDIATE_PATTERN]
    for call, (stream, (subject, durable, _)) in zip(calls, main.SUBSCRIPTIONS.items()):
        assert call.kwargs["stream"] == stream
        assert call.kwargs["durable"] == durable
        assert call.kwargs["manual_ack"] is True
        cfg = call.kwargs["config"]
        assert cfg.durable_name == durable and cfg.filter_subject == subject
        assert cfg.ack_policy == AckPolicy.EXPLICIT
    assert len(svc._subscriptions) == 2
    assert_streams_untouched(svc.js)


async def test_subscribe_reuses_existing_durable():
    svc = service()
    svc.js = mock_js({})
    svc.js.consumer_info = AsyncMock(return_value=SimpleNamespace(config=SimpleNamespace(
        filter_subject=main.RESPONSE_QUEUE_PATTERN, ack_policy=AckPolicy.EXPLICIT, deliver_subject="_INBOX.x")))
    svc.js.subscribe = AsyncMock(return_value=MagicMock())
    await svc.subscribe_stream("RESPONSE_QUEUE")
    assert svc.js.subscribe.await_args.kwargs["config"] is None
    assert_streams_untouched(svc.js)


async def test_subscribe_incompatible_durable_is_error_not_deleted():
    svc = service()
    svc.js = mock_js({})
    svc.js.consumer_info = AsyncMock(return_value=SimpleNamespace(config=SimpleNamespace(
        filter_subject="puda.x.cmd.response.queue", ack_policy=AckPolicy.EXPLICIT, deliver_subject="_INBOX.x")))
    svc.js.subscribe = AsyncMock()
    with pytest.raises(RuntimeError, match="Incompatible"):
        await svc.subscribe_stream("RESPONSE_QUEUE")
    svc.js.subscribe.assert_not_called()
    assert_streams_untouched(svc.js)


def test_never_subscribes_to_immediate_ping_or_update_subjects():
    subjects = [sub for sub, _, _ in main.SUBSCRIPTIONS.values()]
    assert subjects == ["puda.*.cmd.response.queue", "puda.*.cmd.response.immediate"]
    for subject in subjects:
        assert not subject.endswith(".cmd.immediate")
        assert "ping" not in subject and "update" not in subject


async def test_keyring_rotation_record_is_adopted(tmp_path):
    key = key_file(tmp_path)
    svc = service(key=str(key))
    old = e2e.Context(str(key)).current().encrypt
    new = os.urandom(32)
    record = json.dumps({
        "new_key": base64.b64encode(new).decode(),
        "old_key": base64.b64encode(old).decode(),
        "encrypt_kid": e2e.kid_for(new).hex(),
    }).encode()
    sealed = e2e.Context(str(key)).seal(e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), record)
    kv = MagicMock()
    kv.get = AsyncMock(return_value=SimpleNamespace(value=sealed))
    svc.js = MagicMock()
    svc.js.key_value = AsyncMock(return_value=kv)
    await svc.sync_keyring()
    assert svc.encryption.current().encrypt == new
    kv.get.assert_awaited_once_with("current")
