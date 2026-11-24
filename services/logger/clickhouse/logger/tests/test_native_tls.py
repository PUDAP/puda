import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import nats
import pytest
from nats.js.api import StreamConfig, RetentionPolicy
from puda import e2e
from native_services import native_services
from native_transport import connect_options
from native_ingest import write_keys, DURABLES
from native_sql import statements
from test_integration import eventually
from test_logger import command

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv('RUN_NATIVE_INTEGRATION') != '1', reason='isolated native binaries required')]
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['bad-ca', pytest.param('bad-name', marks=pytest.mark.xfail(strict=True, reason='26.10.2.103 native NATS accepts wrong certificate names; deployment blocked'))])
async def test_both_clients_reject_untrusted_tls(tmp_path, mode):
    with native_services(ROOT, tmp_path, tls=mode) as (config, db):
        with pytest.raises(Exception):
            await nats.connect(**connect_options(tmp_path/'transport.xml', config.servers[0]))
        sql = "CREATE TABLE puda.reject (payload String) ENGINE=NATS(puda_native_nats) SETTINGS nats_subjects='test', nats_format='RawBLOB', nats_flush_interval_ms=100"
        if mode == 'bad-name':
            # Use an explicit test publisher identity matching the bad leaf;
            # the engine still addresses 127.0.0.1 and MUST reject that leaf.
            options = connect_options(tmp_path/'transport.xml', config.servers[0])
            publisher = await nats.connect(**options, tls_hostname='wrong.invalid')
            try:
                db.request(sql)
                db.request('CREATE TABLE puda.tls_probe (payload String) ENGINE=MergeTree ORDER BY tuple()')
                db.request('CREATE MATERIALIZED VIEW puda.tls_probe_mv TO puda.tls_probe AS SELECT payload FROM puda.reject')
                for _ in range(30):
                    await publisher.publish('test', b'isolated-name-verification-probe')
                    await publisher.flush()
                    await asyncio.sleep(0.1)
                count = int(db.request('SELECT count() FROM puda.tls_probe'))
                assert count == 0, f'Native engine persisted {count} messages from a wrong-name TLS peer'
            finally:
                await publisher.close()
            return
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(db.request, sql)
        # Establish that rejection was a TLS failure, not SQL syntax/settings.
        db.request('SYSTEM FLUSH LOGS')
        logs = db.request("SELECT exception FROM system.query_log WHERE type='ExceptionBeforeStart' OR type='ExceptionWhileProcessing' FORMAT TSV").decode()
        assert 'SSL' in logs or 'TLS' in logs or 'certificate' in logs, logs


@pytest.mark.asyncio
@pytest.mark.parametrize('retention', [RetentionPolicy.LIMITS, RetentionPolicy.INTEREST])
async def test_tls_encrypted_ingestion_storage_retry_and_remote_sync(tmp_path, retention, monkeypatch):
    import native_control
    with native_services(ROOT, tmp_path, tls='good') as (config, db):
        nc = await nats.connect(**connect_options(tmp_path/'transport.xml', config.servers[0]))
        key = os.urandom(32)
        e2e.set_ring(e2e.Ring(key))
        try:
            js = nc.jetstream()
            for suffix in ('queue','immediate'):
                await js.add_stream(config=StreamConfig(name='RESPONSE_'+suffix.upper(), subjects=['puda.*.cmd.response.'+suffix], retention=retention))
            other = await js.pull_subscribe('puda.*.cmd.response.queue', durable='other', stream='RESPONSE_QUEUE')
            keys = tmp_path/'user_files'/'puda-keys.tsv'
            write_keys(keys, [key])
            password = tmp_path/'password'
            password.write_text(config.password)
            password.chmod(0o600)
            args = SimpleNamespace(action='install', server=config.servers[0], url=config.url,user=config.user,
                password_file=str(password),keys=str(keys),transport=str(tmp_path/'transport.xml'),
                local_ca=None,remote_target=None,remote_key_path=None)
            # Test engine capabilities directly; production CLI is fail-closed
            # while the independent hostname-negative regression remains xfail.
            from native_ingest import provision_consumers
            await provision_consumers(js)
            for sql in statements(config.servers[0], str(keys), 'puda_native_nats'):
                db.request(sql)
            subject = 'puda.robot.cmd.response.queue'
            raw = json.dumps(command()).encode()
            db.request('ALTER TABLE puda.command_logs ADD CONSTRAINT tls_outage CHECK 0')
            await js.publish(subject,e2e.seal(subject,raw))
            await (await other.fetch(1,timeout=3))[0].ack_sync()
            async def failed():
                return 'tls_outage' in (tmp_path/'error.log').read_text()
            await eventually(failed)
            info = await js.consumer_info('RESPONSE_QUEUE',DURABLES['RESPONSE_QUEUE'])
            assert info.num_ack_pending == 1 and info.ack_floor.stream_seq == 0
            assert db.request('SELECT count() FROM puda.command_logs').strip() == b'0'
            db.request('ALTER TABLE puda.command_logs DROP CONSTRAINT tls_outage')
            async def recovered():
                info = await js.consumer_info('RESPONSE_QUEUE',DURABLES['RESPONSE_QUEUE'])
                return db.request('SELECT count() FROM puda.command_logs').strip() == b'1' and info.num_ack_pending == 0
            await eventually(recovered)
            assert json.loads(db.request('SELECT raw_json FROM puda.command_logs FORMAT JSONEachRow'))['raw_json'] == raw.decode()
            assert (await js.stream_info('RESPONSE_QUEUE')).config.retention == retention
            # Agent-local dictionary and remote dictionary are distinct paths.
            # Execute the real one-shot install helper, only substituting SSH.
            import base64
            import hashlib
            import native_remote
            from native_key_install import install as install_keys
            next_key = os.urandom(32)
            kv = await js.create_key_value(bucket='E2E_KEYRING')
            record = json.dumps({'new_key':base64.b64encode(next_key).decode(),
                'old_key':base64.b64encode(key).decode(),
                'encrypt_kid':hashlib.sha256(next_key).digest()[:4].hex()}).encode()
            await kv.put('current', e2e.seal('kv:E2E_KEYRING:current',record))
            local_keys = tmp_path/'agent.tsv'
            write_keys(local_keys,[key])
            keys.parent.chmod(0o700)
            transfers = []
            def transfer(path, target):
                assert target == 'isolated-test-remote'
                transfers.append(install_keys(Path(path).read_bytes(),keys))
            def failed_transfer(path, target):
                raise RuntimeError('isolated transfer failed')
            monkeypatch.setattr(native_remote,'publish_keys',failed_transfer)
            args.action, args.keys = 'sync', str(local_keys)
            args.remote_target, args.remote_key_path = 'isolated-test-remote', str(keys)
            with pytest.raises(RuntimeError, match='Native key sync failed'):
                await native_control.install(args)
            assert int(db.request('SELECT count() FROM puda_native_secrets.keys')) == 1
            monkeypatch.setattr(native_remote,'publish_keys',transfer)
            # Retry reads the retained local archive and installs it remotely.
            await native_control.install(args)
            assert len(transfers) == 1
            e2e.set_ring(e2e.Ring(next_key,previous=key))
            await js.publish(subject,e2e.seal(subject,raw))
            async def rotated():
                return int(db.request('SELECT count() FROM puda.command_logs')) == 2
            await eventually(rotated)
            db.request('SYSTEM FLUSH LOGS')
            logs = db.request('SELECT query,exception FROM system.query_log FORMAT TSV').decode()
            for filename in ('server.log','error.log'):
                logs += (tmp_path/filename).read_text()
            assert key.hex() not in logs and next_key.hex() not in logs
        finally:
            e2e.set_ring(None)
            await nc.close()
