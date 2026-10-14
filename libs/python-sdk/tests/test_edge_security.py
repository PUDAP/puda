import base64
import json
import ssl
from unittest.mock import AsyncMock, patch

import pytest

from puda import EdgeNatsClient
from puda import e2e
from puda.host_addresses import HostAddresses


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("PUDA_NATS_CA", raising=False)
    monkeypatch.delenv("PUDA_E2E_KEY_FILE", raising=False)


def key_file(tmp_path, name, byte):
    path = tmp_path / name
    path.write_text("encrypt=" + base64.b64encode(bytes([byte]) * 32).decode() + "\n")
    return str(path)


def client(key="", **kwargs):
    return EdgeNatsClient(["nats://localhost:4222"], "test", e2e_key_file=key, **kwargs)


def test_independent_clients_and_environment_override(tmp_path, monkeypatch):
    first = key_file(tmp_path, "first.key", 1)
    second = key_file(tmp_path, "second.key", 2)
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", first)
    a, b, plain = client(None), client(second), client("")
    subject = "puda.test.tlm.stream.pos"
    frame = a.encryption.seal(subject, b'{"x":1}')
    assert a.encryption.open_payload(subject, frame) == b'{"x":1}'
    with pytest.raises(e2e.E2EError):
        b.encryption.open_payload(subject, frame)
    assert plain.encryption.seal(subject, b"hello") == b"hello"
    assert a.encryption.current().path != b.encryption.current().path


def test_invalid_keys_fail_without_plaintext_fallback(tmp_path, monkeypatch):
    for content in ("", "encrypt=bad", "encrypt="):
        path = tmp_path / "bad.key"
        path.write_text(content)
        with pytest.raises(e2e.E2EError):
            client(str(path))
    monkeypatch.setenv("PUDA_E2E_KEY_FILE", str(tmp_path / "missing"))
    with pytest.raises(e2e.E2EError):
        client(None)
    assert not client("").encryption.enabled()


def test_tls_independent_of_e2ee_and_environment(monkeypatch):
    monkeypatch.setenv("PUDA_NATS_CA", "/environment/ca.pem")
    with patch.object(ssl, "create_default_context") as create:
        tls = EdgeNatsClient(["tls://broker:4222"], "test", ca_file="/explicit/ca.pem")
        create.assert_called_once_with(cafile="/explicit/ca.pem")
        assert tls._connect_kwargs == {"tls": create.return_value}
        assert not tls.encryption.enabled()
    with patch.object(ssl, "create_default_context") as create:
        EdgeNatsClient(["tls://broker:4222"], "test")
        create.assert_called_once_with(cafile="/environment/ca.pem")
    with pytest.raises(e2e.E2EError):
        EdgeNatsClient(["tls://broker:4222"], "test", ca_file="")
    with pytest.raises(e2e.E2EError):
        EdgeNatsClient(["tls://broker:4222", "nats://broker:4222"], "test", ca_file="")
    assert client(ca_file="")._connect_kwargs == {}


def test_invalid_certificate_fails_before_connect(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("not a certificate")
    with pytest.raises(ssl.SSLError):
        EdgeNatsClient(["tls://broker:4222"], "test", ca_file=str(ca))


def test_rotation_persists_only_to_own_file(tmp_path):
    a = client(key_file(tmp_path, "a.key", 1))
    b = client(key_file(tmp_path, "b.key", 2))
    old, new = bytes([1]) * 32, bytes([3]) * 32
    frame = a.encryption.seal("subject", b"old")
    record = json.dumps({
        "new_key": base64.b64encode(new).decode(),
        "old_key": base64.b64encode(old).decode(),
        "encrypt_kid": e2e.kid_hex(e2e.kid_for(new)),
    }).encode()
    assert a.encryption.adopt_record(record)
    assert not a.encryption.adopt_record(record)
    assert a.encryption.open_payload("subject", frame) == b"old"
    reloaded = client(str(tmp_path / "a.key"))
    assert reloaded.encryption.current().encrypt == new
    assert b.encryption.current().encrypt == bytes([2]) * 32
    assert client(str(tmp_path / "b.key")).encryption.current().encrypt == bytes([2]) * 32
    a.encryption.drop_previous()
    with pytest.raises(e2e.E2EError):
        a.encryption.open_payload("subject", frame)
    assert client(str(tmp_path / "a.key")).encryption.current().previous is None


def test_telemetry_and_ping_use_client_context(tmp_path):
    import asyncio
    from types import SimpleNamespace

    async def exercise():
        edge = client(key_file(tmp_path, "key", 1))
        edge.nc = SimpleNamespace(is_connected=True, publish=AsyncMock())
        assert await edge._publish("puda.test.tlm.stream.pos", {"x": 1})
        sent = edge.nc.publish.call_args.kwargs
        assert json.loads(edge.encryption.open_payload(sent["subject"], sent["payload"]))["x"] == 1
        msg = SimpleNamespace(subject=edge.ping, reply="_INBOX.test", respond=AsyncMock())
        msg.data = edge.encryption.seal(msg.subject, b"ping")
        with patch.object(edge, "_host_addresses", AsyncMock(return_value=HostAddresses())):
            await edge._handle_ping(msg)
        body = msg.respond.call_args.args[0]
        assert json.loads(edge.encryption.open_payload(msg.reply, body))["status"] == "pong"
        edge.kv_state = SimpleNamespace(put=AsyncMock())
        await edge.publish_state({"state": "idle"})
        stored = edge.kv_state.put.call_args.args[1]
        aad = e2e.kv_aad(edge.kv_bucket_state, edge.machine_id)
        assert json.loads(edge.encryption.open_payload(aad, stored))["state"] == "idle"
        edge.kv_commands = SimpleNamespace(put=AsyncMock())
        await edge.publish_commands({"catalog": []})
        stored = edge.kv_commands.put.call_args.args[1]
        aad = e2e.kv_aad(edge.kv_bucket_commands, edge.machine_id)
        assert json.loads(edge.encryption.open_payload(aad, stored)) == {"catalog": []}

        from puda.models import (
            CommandResponse, CommandResponseStatus, MessageHeader, MessageType, NATSMessage,
        )
        from puda.edge_updater import EdgeUpdater

        original = NATSMessage(header=MessageHeader(
            message_type=MessageType.COMMAND, machine_id="test",
            user_id="test", username="test", run_id="test",
        ))
        response = CommandResponse(status=CommandResponseStatus.SUCCESS)
        edge.js = SimpleNamespace(publish=AsyncMock())
        command = SimpleNamespace(subject="puda.test.cmd.immediate")
        command.data = edge.encryption.seal(command.subject, original.model_dump_json().encode())
        await edge.commands._publish_command_response(command, response, edge.response_immediate)
        sent = edge.js.publish.call_args.kwargs
        decoded = edge.encryption.open_payload(sent["subject"], sent["payload"])
        assert NATSMessage.model_validate_json(decoded).response.status == CommandResponseStatus.SUCCESS
        await EdgeUpdater(edge)._publish_response(original, response)
        sent = edge.nc.publish.call_args.kwargs
        decoded = edge.encryption.open_payload(sent["subject"], sent["payload"])
        assert NATSMessage.model_validate_json(decoded).response.status == CommandResponseStatus.SUCCESS

    asyncio.run(exercise())
