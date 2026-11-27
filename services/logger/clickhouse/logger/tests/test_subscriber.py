import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nats.js.api import AckPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError
from puda import e2e

from e2e_context import ring_context
from test_logger import command


def message(subject="puda.robot.cmd.response.queue", data=None):
    return SimpleNamespace(
        subject=subject,
        data=json.dumps(command()).encode() if data is None else data,
        ack=AsyncMock(),
        nak=AsyncMock(),
        term=AsyncMock(),
    )


def service():
    from subscriber import Config, Subscriber

    return Subscriber(
        Config(
            ["nats://127.0.0.1:14222"], "http://127.0.0.1:18123", "test", "fake-secret"
        )
    )


@pytest.mark.asyncio
async def test_ack_only_after_write_and_failure_naks_without_leaking(caplog):
    sub = service()
    msg = message()
    writes = []

    def write(rows):
        assert not msg.ack.called
        writes.extend(rows)

    sub.sink.write = write
    await sub.process_batch([(msg, True)])
    assert len(writes) == 1
    msg.ack.assert_awaited_once()
    msg.ack.reset_mock()

    def failed(_):
        raise RuntimeError("fake-secret and secret-payload")

    sub.sink.write = failed
    await sub.process_batch([(msg, True)])
    msg.ack.assert_not_called()
    msg.nak.assert_awaited_once_with(delay=5)
    assert "fake-secret" not in caplog.text and "secret-payload" not in caplog.text


@pytest.mark.asyncio
async def test_invalid_response_terminated_but_valid_batch_persists(caplog):
    sub = service()
    bad, good = message(data=b'{"secret-payload":'), message()
    rows = []
    sub.sink.write = rows.extend
    await sub.process_batch([(bad, True), (good, True)])
    bad.term.assert_awaited_once()
    bad.ack.assert_not_called()
    good.ack.assert_awaited_once()
    assert len(rows) == 1 and "secret-payload" not in caplog.text


@pytest.mark.asyncio
async def test_e2ee_rotation_refresh_retry_and_retirement(tmp_path):
    sub = service()
    sub.config.encrypted = True
    old, new = b"o" * 32, b"n" * 32
    keyfile = tmp_path / "e2e.key"
    keyfile.write_text("encrypt=" + base64.b64encode(old).decode() + "\n")
    record = json.dumps(
        {
            "new_key": base64.b64encode(new).decode(),
            "old_key": base64.b64encode(old).decode(),
            "encrypt_kid": e2e.kid_for(new).hex(),
        }
    ).encode()
    sub.config.context = e2e.Context(keyfile)
    encrypted_record = sub.config.context.seal(
        e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), record
    )
    kv = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(value=encrypted_record))
    )
    sub.js = SimpleNamespace(key_value=AsyncMock(return_value=kv))
    msg = message()
    msg.data = ring_context(e2e.Ring(new)).seal(msg.subject, msg.data)
    rows = []
    sub.sink.write = rows.extend
    await sub.process_batch([(msg, True)])
    assert rows and sub.config.context.current().encrypt == new
    assert sub.config.context.current().previous == old
    assert base64.b64encode(new).decode() in keyfile.read_text()
    msg.ack.assert_awaited_once()
    kv.get.side_effect = NotFoundError
    await sub.sync_keyring()
    assert sub.config.context.current().previous is None
    msg.data = b"plaintext rejected in E2EE"
    await sub.process_batch([(msg, True)])
    msg.nak.assert_awaited_once_with(delay=5)


@pytest.mark.asyncio
async def test_batch_flushes_on_threshold_and_timer():
    sub = service()
    sub.config.batch_size = 2
    sub.config.batch_interval = 0.05
    writes, event = [], asyncio.Event()

    async def process(batch):
        writes.append(batch)
        event.set()

    sub.process_batch = process
    worker = asyncio.create_task(sub.worker())
    try:
        await sub.receive(message())
        await asyncio.sleep(0.01)
        assert not writes
        await sub.receive(message())
        await asyncio.wait_for(event.wait(), 1)
        assert len(writes[0]) == 2
        event.clear()
        await sub.receive(message())
        await asyncio.wait_for(event.wait(), 1)
        assert len(writes[1]) == 1
        await asyncio.wait_for(sub.queue.join(), 1)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def stream_js(configs):
    async def stream_info(name):
        if name not in configs:
            raise NotFoundError
        return SimpleNamespace(config=configs[name])

    return SimpleNamespace(
        stream_info=AsyncMock(side_effect=stream_info),
        add_stream=AsyncMock(),
        update_stream=AsyncMock(),
        delete_stream=AsyncMock(),
        consumer_info=AsyncMock(side_effect=NotFoundError),
        add_consumer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_missing_streams_created_with_spec_settings_and_warning(caplog):
    from subscriber import RESPONSE_CONSUMERS, RESPONSE_STREAMS

    sub = service()
    sub.js = stream_js({})
    await sub.ensure_streams()
    assert len(sub.js.add_stream.call_args_list) == 2
    for call in sub.js.add_stream.call_args_list:
        config = call.kwargs["config"]
        assert config.subjects == [RESPONSE_STREAMS[config.name]]
        assert config.retention == RetentionPolicy.INTEREST
        assert config.storage == StorageType.FILE
        assert config.max_age == 86400
    assert caplog.text.count("unprovisioned") == 2
    sub.js.update_stream.assert_not_called()
    sub.js.delete_stream.assert_not_called()
    for call in sub.js.add_consumer.call_args_list:
        config = call.kwargs["config"]
        assert config.ack_policy == AckPolicy.EXPLICIT
        assert config.durable_name.startswith("clickhouse_")
        assert config.deliver_group == config.durable_name
        assert config.max_deliver == -1
    assert not any(
        name.startswith("puda_logger") for name in RESPONSE_CONSUMERS.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("retention,subjects", [
    (RetentionPolicy.WORK_QUEUE, None),
    (RetentionPolicy.INTEREST, ["puda.*.cmd.response.other"]),
])
async def test_workqueue_or_wrong_subject_fails_closed_without_mutation(retention, subjects):
    from subscriber import RESPONSE_STREAMS

    sub = service()
    sub.js = stream_js({
        name: StreamConfig(name=name, subjects=subjects or [subject], retention=retention)
        for name, subject in RESPONSE_STREAMS.items()
    })
    with pytest.raises(ValueError):
        await sub.ensure_streams()
    sub.js.add_stream.assert_not_called()
    sub.js.update_stream.assert_not_called()
    sub.js.delete_stream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("retention,max_age,mismatch", [
    (RetentionPolicy.INTEREST, 86400, False),
    (RetentionPolicy.INTEREST, 7200, True),
    (RetentionPolicy.LIMITS, 86400, True),
])
async def test_existing_streams_left_unchanged_and_mismatch_logged(
    caplog, retention, max_age, mismatch
):
    from subscriber import RESPONSE_STREAMS

    sub = service()
    configs = {
        name: StreamConfig(name=name, subjects=[subject], retention=retention,
                           storage=StorageType.FILE, max_age=max_age)
        for name, subject in RESPONSE_STREAMS.items()
    }
    sub.js = stream_js(configs)
    await sub.ensure_streams()
    sub.js.add_stream.assert_not_awaited()
    sub.js.update_stream.assert_not_called()
    sub.js.delete_stream.assert_not_called()
    assert sub.js.add_consumer.await_count == 2
    assert all(c.retention == retention and c.max_age == max_age for c in configs.values())
    assert (caplog.text.count("leaving it unchanged") == 2) is mismatch


@pytest.mark.asyncio
async def test_subscriptions_never_use_machine_jetstream_consumers():
    from subscriber import RESPONSE_CONSUMERS

    sub = service()
    sub.nc = SimpleNamespace(subscribe=AsyncMock())
    sub.js = SimpleNamespace(subscribe=AsyncMock())
    await sub.subscribe()
    calls = sub.nc.subscribe.call_args_list
    assert {c.args[0] for c in calls} == {
        "puda.*.cmd.queue",
        "puda.*.tlm.health",
        "puda.*.tlm.stream.>",
    }
    # Observers must never subscribe to immediate, ping or update subjects (§8.3).
    subjects = [c.args[0] for c in calls + sub.js.subscribe.call_args_list]
    assert not any(
        s.endswith((".cmd.immediate", ".cmd.ping", ".update", ".update.response", ">"))
        and s != "puda.*.tlm.stream.>"
        for s in subjects
    )
    assert all(c.kwargs["queue"].startswith("clickhouse_") for c in calls)
    assert len(sub.js.subscribe.call_args_list) == 2
    for call in sub.js.subscribe.call_args_list:
        assert call.kwargs["manual_ack"] is True
        assert ".cmd.response." in call.args[0]
        assert call.kwargs["durable"] in RESPONSE_CONSUMERS.values()
