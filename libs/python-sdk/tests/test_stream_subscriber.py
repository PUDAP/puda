"""StreamSubscriber: never ack on failure, never delete durables, no re-subscribe on reconnect."""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nats.js.errors
import pytest

from puda import StreamSubscriber, e2e

KEY = base64.b64encode(bytes(range(32))).decode()
NEW_KEY = base64.b64encode(bytes(range(1, 33))).decode()


class Recorder(StreamSubscriber):
    def __init__(self, *args, fail=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail = fail
        self.seen = []
        self.starts = 0

    async def handle_message(self, msg, stream, subject):
        self.seen.append(msg.data)
        if self.fail:
            raise RuntimeError("database down")
        await msg.ack()

    async def on_start(self):
        self.starts += 1

    async def on_stop(self):
        pass


def fake_msg(data: bytes, subject="puda.m1.cmd.response.queue"):
    return SimpleNamespace(
        subject=subject, data=data, ack=AsyncMock(), nak=AsyncMock(), term=AsyncMock()
    )


def connected(service, js=None):
    service.nc = MagicMock(is_closed=False)
    service.js = js or MagicMock()
    service._is_connected = True
    return service


async def subscribed_callback(service, durable="logger_q"):
    js = MagicMock()
    js.subscribe = AsyncMock(return_value=MagicMock())
    connected(service, js)
    await service.subscribe("RESPONSE_QUEUE", "puda.*.cmd.response.queue", durable)
    kwargs = js.subscribe.await_args.kwargs
    return kwargs, kwargs["cb"]


def key_file(tmp_path, key=KEY):
    path = tmp_path / "e2e.key"
    path.write_text(f"encrypt={key}\n")
    path.chmod(0o600)
    return path


def test_subscribes_with_manual_ack_and_durable():
    service = Recorder(["nats://localhost:4222"])
    kwargs, _ = asyncio.run(subscribed_callback(service))
    assert kwargs["manual_ack"] is True
    assert kwargs["durable"] == "logger_q"
    assert kwargs["stream"] == "RESPONSE_QUEUE"


def test_successful_handler_acks_once():
    service = Recorder(["nats://localhost:4222"])
    _, cb = asyncio.run(subscribed_callback(service))
    msg = fake_msg(b'{"ok": true}')
    asyncio.run(cb(msg))
    assert service.seen == [b'{"ok": true}']
    msg.ack.assert_awaited_once()
    msg.nak.assert_not_awaited()


def test_failed_handler_is_nakked_not_acked():
    service = Recorder(["nats://localhost:4222"], fail=True)
    _, cb = asyncio.run(subscribed_callback(service))
    msg = fake_msg(b"{}")
    asyncio.run(cb(msg))
    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once_with(delay=service.nak_delay)


def test_unopenable_payload_is_nakked_and_handler_skipped(tmp_path):
    service = Recorder(["nats://localhost:4222"], e2e_key_file=key_file(tmp_path))
    service._refresh_keyring = AsyncMock()
    _, cb = asyncio.run(subscribed_callback(service))
    msg = fake_msg(b'{"plaintext": true}')
    asyncio.run(cb(msg))
    assert service.seen == []
    service._refresh_keyring.assert_awaited_once()
    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once()


def test_sealed_payload_is_opened_before_the_handler(tmp_path):
    service = Recorder(["nats://localhost:4222"], e2e_key_file=key_file(tmp_path))
    _, cb = asyncio.run(subscribed_callback(service))
    subject = "puda.m1.cmd.response.queue"
    msg = fake_msg(service.encryption.seal(subject, b'{"a": 1}'), subject)
    asyncio.run(cb(msg))
    assert service.seen == [b'{"a": 1}']
    msg.ack.assert_awaited_once()


def test_already_bound_durable_is_never_deleted():
    service = Recorder(["nats://localhost:4222"])
    js = MagicMock()
    js.subscribe = AsyncMock(
        side_effect=nats.js.errors.Error("consumer is already bound to a subscription")
    )
    js.delete_consumer = AsyncMock()
    connected(service, js)
    with pytest.raises(RuntimeError, match="already bound"):
        asyncio.run(service.subscribe("RESPONSE_QUEUE", "puda.*.cmd.response.queue", "logger_q"))
    js.delete_consumer.assert_not_awaited()
    assert js.subscribe.await_count == 1


def test_reconnect_does_not_resubscribe_or_clear():
    service = Recorder(["nats://localhost:4222"])
    connected(service)
    sub = MagicMock()
    service._subscriptions.append(sub)
    service.subscribe = AsyncMock()
    asyncio.run(service._reconnected_callback())
    service.subscribe.assert_not_awaited()
    assert service._subscriptions == [sub]
    assert service._is_connected


def test_connect_reuses_a_reconnecting_connection(monkeypatch):
    service = Recorder(["nats://localhost:4222"])
    service.nc = MagicMock(is_closed=False)
    service._is_connected = False  # disconnected callback fired; nats-py is reconnecting
    opened = AsyncMock()
    monkeypatch.setattr("puda.stream_subscriber.nats.connect", opened)
    assert asyncio.run(service.connect()) is True
    opened.assert_not_awaited()


def test_run_connects_again_only_after_the_connection_closes(monkeypatch):
    service = Recorder(["nats://localhost:4222"])
    connections = []

    async def fake_connect(**kwargs):
        nc = MagicMock(is_closed=False)
        nc.jetstream.return_value = MagicMock()
        nc.close = AsyncMock()
        connections.append(nc)
        return nc

    monkeypatch.setattr("puda.stream_subscriber.nats.connect", fake_connect)

    async def scenario():
        task = asyncio.create_task(service.run(health_check_interval=0.01))
        await asyncio.sleep(0.05)
        service._is_connected = False  # reconnecting: must not open a second connection
        await asyncio.sleep(0.05)
        assert len(connections) == 1 and service.starts == 1
        connections[0].is_closed = True  # nats-py gave up
        await asyncio.sleep(0.05)
        service._should_run = False
        await task

    asyncio.run(scenario())
    assert len(connections) == 2
    assert service.starts == 2


def test_keyring_record_is_adopted(tmp_path):
    path = key_file(tmp_path)
    service = Recorder(["nats://localhost:4222"], e2e_key_file=path)
    record = (
        '{"new_key": "%s", "old_key": "%s", "encrypt_kid": "%s"}'
        % (NEW_KEY, KEY, e2e.kid_hex(e2e.kid_for(base64.b64decode(NEW_KEY))))
    ).encode()
    sealed = service.encryption.seal(e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), record)
    kv = MagicMock()
    kv.get = AsyncMock(return_value=SimpleNamespace(value=sealed))
    connected(service)
    asyncio.run(service._refresh_keyring(kv))
    ring = service.encryption.current()
    assert ring.encrypt == base64.b64decode(NEW_KEY)
    assert "encrypt=" + NEW_KEY in path.read_text()


def test_missing_keyring_record_drops_previous(tmp_path):
    path = tmp_path / "e2e.key"
    path.write_text(f"encrypt={KEY}\nprevious={NEW_KEY}\n")
    path.chmod(0o600)
    service = Recorder(["nats://localhost:4222"], e2e_key_file=path)
    kv = MagicMock()
    kv.get = AsyncMock(side_effect=nats.js.errors.NotFoundError())
    connected(service)
    asyncio.run(service._refresh_keyring(kv))
    assert service.encryption.current().previous is None
