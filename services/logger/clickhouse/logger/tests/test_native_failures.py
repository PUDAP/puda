"""Poison responses remain pending; key rotation retries without a worker."""
import asyncio
import hashlib
import json
import os

import nats
import pytest
from nats.js.api import RetentionPolicy, StreamConfig
from puda import e2e
import native_ingest
from test_integration import services, eventually
from test_logger import command

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_NATIVE_INTEGRATION') != '1', reason='requires isolated native services')]


@pytest.mark.asyncio
async def test_consumer_provisioning_refuses_unsafe_existing_config(services):
    from nats.js.api import ConsumerConfig, AckPolicy
    config, _ = services
    nc = await nats.connect(servers=config.servers)
    try:
        js = nc.jetstream()
        await js.add_stream(config=StreamConfig(name='RESPONSE_QUEUE', subjects=['puda.*.cmd.response.queue'], retention=RetentionPolicy.WORK_QUEUE))
        with pytest.raises(ValueError, match='WorkQueue'):
            await native_ingest.provision_consumers(js)
        assert (await js.stream_info('RESPONSE_QUEUE')).state.consumer_count == 0
        await js.delete_stream('RESPONSE_QUEUE')
        for suffix in ('QUEUE','IMMEDIATE'):
            await js.add_stream(config=StreamConfig(name='RESPONSE_' + suffix, subjects=['puda.*.cmd.response.' + suffix.lower()]))
        await native_ingest.provision_consumers(js)
        await native_ingest.provision_consumers(js)
        await js.add_consumer('RESPONSE_QUEUE', config=ConsumerConfig(
            durable_name=native_ingest.DURABLES['RESPONSE_QUEUE'],
            filter_subject='puda.*.cmd.response.queue', ack_policy=AckPolicy.EXPLICIT,
            ack_wait=2, max_ack_pending=1, max_deliver=1))
        with pytest.raises(ValueError, match='incompatible'):
            await native_ingest.provision_consumers(js)
        assert (await js.consumer_info('RESPONSE_QUEUE',native_ingest.DURABLES['RESPONSE_QUEUE'])).config.max_deliver == 1
    finally:
        await nc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('retention', [RetentionPolicy.LIMITS, RetentionPolicy.INTEREST])
@pytest.mark.parametrize('failure', ['missing', 'subject', 'tamper', 'key', 'keyid', 'json', 'schema', 'timestamp', 'clock', 'month', 'day', 'storage'])
async def test_rejected_response_is_not_acked(services, tmp_path, retention, failure):
    config, db = services
    nc = await nats.connect(servers=config.servers)
    key, next_key = os.urandom(32), os.urandom(32)
    path = tmp_path / 'user_files' / 'puda-keys.tsv'
    e2e.set_ring(e2e.Ring(key))
    try:
        js = nc.jetstream()
        for suffix in ('QUEUE', 'IMMEDIATE'):
            await js.add_stream(config=StreamConfig(name='RESPONSE_' + suffix,
                subjects=['puda.*.cmd.response.' + suffix.lower()], retention=retention))
        other = await js.pull_subscribe('puda.*.cmd.response.queue',
            durable='puda_logger_existing', stream='RESPONSE_QUEUE')
        await native_ingest.provision_consumers(js)
        native_ingest.write_keys(path, [] if failure == 'missing' else [key])
        subject = 'puda.robot.cmd.response.queue'
        raw = json.dumps(command()).encode()
        frame = e2e.seal(subject if failure != 'subject' else 'puda.other.cmd.response.queue', raw)
        if failure == 'tamper':
            frame = frame[:-1] + bytes([frame[-1] ^ 1])
        if failure == 'key':
            path.write_text(hashlib.sha256(key).digest()[:4].hex().upper() + '\t' + next_key.hex() + '\n')
        if failure == 'keyid':
            frame = frame[:2] + b'FAKE' + frame[6:]
            path.write_text(b'FAKE'.hex().upper() + '\t' + key.hex() + '\n')
        if failure in ('json', 'schema', 'timestamp', 'clock', 'month', 'day'):
            bad = command()
            if failure == 'json':
                bad['command']['step_number'] = True
            elif failure == 'schema':
                bad['header']['machine_id'] = 123
            else:
                bad['header']['timestamp'] = {
                    'timestamp': '2026-07-07 09:41:42',
                    'clock': '2026-01-01T23:60:00Z',
                    'month': '2026-00-01T12:00:00Z',
                    'day': '2026-01-00T12:00:00Z',
                }[failure]
            frame = e2e.seal(subject, json.dumps(bad).encode())
        for sql in native_ingest.statements(config.servers[0], path):
            db.request(sql)
        if failure == 'storage':
            db.request('ALTER TABLE puda.command_logs ADD CONSTRAINT native_outage CHECK 0')
        await js.publish(subject, frame)
        copy = (await other.fetch(1, timeout=3))[0]
        await copy.ack_sync()
        async def failure_observed():
            return ('native_outage' if failure == 'storage' else 'Native ') in (tmp_path / 'error.log').read_text()
        await eventually(failure_observed, timeout=8)
        info = await js.consumer_info('RESPONSE_QUEUE', native_ingest.DURABLES['RESPONSE_QUEUE'])
        assert info.num_ack_pending == 1 and info.ack_floor.stream_seq == 0
        assert db.request('SELECT count() FROM puda.command_logs').strip() == b'0'
        assert (await js.stream_info('RESPONSE_QUEUE')).state.messages == 1
        assert (await js.stream_info('RESPONSE_QUEUE')).config.retention == retention
        if failure == 'missing':
            import base64
            kv = await js.create_key_value(bucket='E2E_KEYRING')
            record = json.dumps({'new_key': base64.b64encode(next_key).decode(),
                'old_key': base64.b64encode(key).decode(),
                'encrypt_kid': hashlib.sha256(next_key).digest()[:4].hex()}).encode()
            await kv.put('current', e2e.seal('kv:E2E_KEYRING:current', record))
            import subprocess
            import sys
            native_ingest.write_keys(path, [key])  # no dictionary reload yet
            password_file = tmp_path / 'http.password'
            password_file.write_text(config.password)
            password_file.chmod(0o600)
            result = subprocess.run([sys.executable,'native_control.py','sync',
                '--server',config.servers[0],'--url',config.url,'--user',config.user,
                '--password-file',str(password_file),'--keys',str(path)], capture_output=True,text=True,timeout=30)
            assert result.returncode == 0, result.stderr
            assert set(native_ingest.read_keys(path)) == {key, next_key}
            async def recovered():
                return db.request('SELECT count() FROM puda.command_logs').strip() == b'1'
            await eventually(recovered)
            e2e.set_ring(e2e.Ring(next_key, previous=key))
            await js.publish(subject, e2e.seal(subject, raw))
            async def rotated():
                return db.request('SELECT count() FROM puda.command_logs').strip() == b'2'
            await eventually(rotated)
        if failure == 'storage':
            db.request('ALTER TABLE puda.command_logs DROP CONSTRAINT native_outage')
            async def persisted():
                info = await js.consumer_info('RESPONSE_QUEUE', native_ingest.DURABLES['RESPONSE_QUEUE'])
                return db.request('SELECT count() FROM puda.command_logs').strip() == b'1' and info.num_ack_pending == 0
            await eventually(persisted)
        db.request('SYSTEM FLUSH LOGS')
        logged = db.request('SELECT query,exception FROM system.query_log FORMAT JSONEachRow').decode()
        metadata = db.request('SHOW CREATE DICTIONARY puda_native_secrets.keys').decode()
        assert key.hex() not in logged + metadata and next_key.hex() not in logged + metadata
        for log in ('server.log', 'error.log'):
            content = (tmp_path / log).read_text()
            assert key.hex() not in content and next_key.hex() not in content
    finally:
        e2e.set_ring(None)
        await nc.close()
