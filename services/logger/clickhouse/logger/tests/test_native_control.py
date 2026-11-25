"""Control plane only: private bootstrap/readback and safe CLI."""
import base64
import hashlib
import os
import subprocess
import sys
import pytest
import native_ingest


def test_private_bootstrap_and_readback(tmp_path):
    source, target = tmp_path / 'sdk.keys', tmp_path / 'dictionary.tsv'
    key = os.urandom(32)
    source.write_text('encrypt=' + base64.b64encode(key).decode() + '\n')
    source.chmod(0o600)
    native_ingest.bootstrap_keys(source, target)
    assert native_ingest.read_keys(target) == [key]
    assert target.stat().st_mode & 0o777 == 0o600
    target.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        native_ingest.read_keys(target)
    with pytest.raises(ValueError):
        list(native_ingest.statements("nats://user:secret@127.0.0.1:4222"))


def test_cli_bootstrap(tmp_path):
    source, target = tmp_path / 'sdk.keys', tmp_path / 'dictionary.tsv'
    key = os.urandom(32)
    source.write_text('encrypt=' + base64.b64encode(key).decode() + '\n')
    source.chmod(0o600)
    result = subprocess.run([sys.executable,'native_control.py','bootstrap','--source',str(source),'--keys',str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert native_ingest.read_keys(target) == [key]
    assert key.hex() not in result.stdout + result.stderr


@pytest.mark.asyncio
async def test_sync_reads_keys_once_without_installation_sql(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    import native_control
    import nats
    import storage
    path = tmp_path / 'keys.tsv'
    key = os.urandom(32)
    native_ingest.write_keys(path, [key])
    password = tmp_path / 'password'
    password.write_text('test-password')
    password.chmod(0o600)
    args = SimpleNamespace(action='sync', server='nats://127.0.0.1:4222',
        url='http://127.0.0.1:8123', user='test', keys=str(path), password_file=str(password))
    read = Mock(wraps=native_ingest.read_keys)
    ddl = Mock(side_effect=AssertionError('sync must not generate installation DDL'))
    nc = SimpleNamespace(jetstream=Mock(return_value=object()), close=AsyncMock())
    connect = AsyncMock(return_value=nc)
    sync = AsyncMock()
    monkeypatch.setattr(native_control, 'read_keys', read)
    monkeypatch.setattr(native_control, 'statements', ddl)
    monkeypatch.setattr(storage, 'ClickHouse', Mock())
    monkeypatch.setattr(nats, 'connect', connect)
    monkeypatch.setattr(native_ingest, 'sync_keys_once', sync)
    await native_control.install(args)
    read.assert_called_once_with(str(path))
    sync.assert_awaited_once()
    assert sync.call_args.args[-1] == [key]
    ddl.assert_not_called()
    nc.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('server', 'nats://remote.example:4222'),
    ('keys', "/private/unsafe'path"),
    ('url', 'http://remote.example:8123'),
])
async def test_control_validates_before_io(monkeypatch, field, value):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import native_control
    args = SimpleNamespace(action='sync', server='nats://127.0.0.1:4222',
        url='http://127.0.0.1:8123', user='test', keys='/private/keys.tsv', password_file='/private/password')
    setattr(args, field, value)
    read = Mock(side_effect=AssertionError('validation must precede file/network I/O'))
    monkeypatch.setattr(native_control, 'read_keys', read)
    with pytest.raises(ValueError):
        await native_control.install(args)
    read.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('exists', [True, False])
async def test_consumer_info_reused_with_post_create_readback(exists):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from nats.js.api import ConsumerConfig, RetentionPolicy, AckPolicy, DeliverPolicy
    from nats.js.errors import NotFoundError
    configs = [ConsumerConfig(durable_name=durable,
        filter_subject='puda.*.cmd.response.' + stream.removeprefix('RESPONSE_').lower(),
        deliver_policy=DeliverPolicy.ALL, ack_policy=AckPolicy.EXPLICIT,
        ack_wait=2, max_deliver=-1, max_ack_pending=1)
        for stream, durable in native_ingest.DURABLES.items()]
    results = [SimpleNamespace(config=c) for c in configs]
    if not exists:
        results = [item for result in results for item in (NotFoundError(), result)]
    js = SimpleNamespace(
        stream_info=AsyncMock(return_value=SimpleNamespace(config=SimpleNamespace(retention=RetentionPolicy.LIMITS))),
        consumer_info=AsyncMock(side_effect=results), add_consumer=AsyncMock())
    await native_ingest.provision_consumers(js)
    assert js.consumer_info.await_count == (2 if exists else 4)
    assert js.add_consumer.await_count == (0 if exists else 2)
