"""Actual encrypted NATS engine -> MV -> existing MergeTree acceptance."""
import asyncio
import json
import os

import nats
import pytest
from nats.js.api import RetentionPolicy, StreamConfig
from puda import e2e
from storage import to_row
from test_integration import services, eventually
from test_logger import command

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_NATIVE_INTEGRATION') != '1', reason='requires isolated native services')]


@pytest.mark.asyncio
async def test_native_encrypted_response(services, tmp_path):
    import native_ingest
    config, db = services
    nc = await nats.connect(servers=config.servers)
    key = os.urandom(32)
    e2e.set_ring(e2e.Ring(key))
    try:
        js = nc.jetstream()
        for suffix in ('QUEUE', 'IMMEDIATE'):
            await js.add_stream(config=StreamConfig(name='RESPONSE_' + suffix,
                subjects=['puda.*.cmd.response.' + suffix.lower()], retention=RetentionPolicy.LIMITS))
        native_ingest.write_keys(tmp_path / 'user_files' / 'puda-keys.tsv', [key])
        import subprocess
        import sys
        password_file = tmp_path / 'http.password'
        password_file.write_text(config.password)
        password_file.chmod(0o600)
        result = subprocess.run([sys.executable, 'native_control.py', 'install',
            '--server', config.servers[0], '--url', config.url, '--user', config.user,
            '--password-file', str(password_file), '--keys', str(tmp_path / 'user_files' / 'puda-keys.tsv')],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        # Existing broad SELECT puda.* readers must not inherit key access.
        db.request('CREATE USER native_reader IDENTIFIED WITH no_password HOST LOCAL')
        db.request('GRANT SELECT ON puda.* TO native_reader')
        from storage import ClickHouse, Config
        reader = ClickHouse(Config(config.servers, config.url, 'native_reader', ''))
        dictionary = json.loads(db.request("SELECT database,name FROM system.dictionaries FORMAT JSONEachRow"))
        with pytest.raises(RuntimeError):
            reader.request(f"SELECT key_hex FROM {dictionary['database']}.{dictionary['name']}")
        with pytest.raises(RuntimeError):
            reader.request(f"SELECT dictGet('{dictionary['database']}.{dictionary['name']}','key_hex',tuple('00000000'))")
        subject = 'puda.robot.cmd.response.queue'
        raw = json.dumps(command(), indent=2).encode()
        await js.publish(subject, e2e.seal(subject, raw))

        async def stored():
            return db.request('SELECT count() FROM puda.command_logs').strip() == b'1'
        await eventually(stored)
        actual = json.loads(db.request('SELECT * FROM puda.command_logs FORMAT JSONEachRow'))
        expected = to_row(subject, raw)
        for name, value in expected.items():
            if name != 'received_ns':
                assert (int(actual[name]) if name in ('event_ns', 'step_number') else actual[name]) == value
        async def acked():
            info = await js.consumer_info('RESPONSE_QUEUE', native_ingest.DURABLES['RESPONSE_QUEUE'])
            return info.num_ack_pending == info.num_pending == 0
        await eventually(acked)
        # Core command taps must not compete with the machine WorkQueue.
        await js.add_stream(config=StreamConfig(name='MACHINE_COMMANDS',
            subjects=['puda.*.cmd.queue'], retention=RetentionPolicy.WORK_QUEUE))
        machine = await js.pull_subscribe('puda.*.cmd.queue', durable='machine', stream='MACHINE_COMMANDS')
        other = await nc.subscribe('puda.*.cmd.queue', queue='existing_python_logger')
        # Core subscriptions have no replay; allow background attachment before publishing.
        await asyncio.sleep(2)
        cases = [('cmd.queue', raw), ('cmd.immediate', raw), ('cmd.response.immediate', raw),
            ('tlm.health', b'{"timestamp":"2026-07-07T11:41:42.123456789+02:00","cpu":4.5,"nested":{"x":null}}'),
            ('tlm.stream.position', b'{"timestamp":"2026-07-07T11:41:42.123456789+02:00","data":{"x":[1,null]}}'),
            ('tlm.stream.legacy', b'{"timestamp":null,"data":{"x":2},"extra":true}')]
        for suffix, plaintext in cases:
            target = 'puda.robot.' + suffix
            await nc.publish(target, e2e.seal(target, plaintext))
        await nc.flush()
        async def all_rows():
            return db.request('SELECT (SELECT count() FROM puda.command_logs)+(SELECT count() FROM puda.telemetry)').strip() == b'7'
        try:
            await eventually(all_rows)
        except AssertionError:
            print(db.request('SELECT subject,count() FROM puda.command_logs GROUP BY subject'))
            print(db.request('SELECT subject,count() FROM puda.telemetry GROUP BY subject'))
            raise
        assert (await machine.fetch(1, timeout=2))[0].data == (await other.next_msg(timeout=2)).data
        for suffix, plaintext in cases:
            target = 'puda.robot.' + suffix
            table = 'command_logs' if suffix.startswith('cmd') else 'telemetry'
            actual = json.loads(db.request(f"SELECT * FROM puda.{table} WHERE subject='{target}' FORMAT JSONEachRow"))
            expected = to_row(target, plaintext)
            for name, value in expected.items():
                if name == 'received_ns' or (name == 'event_ns' and b'null' in plaintext and suffix.endswith('legacy')):
                    continue
                found = actual[name]
                if name in ('event_ns', 'step_number'):
                    found = int(found)
                if name == 'data':
                    found, value = json.loads(found), json.loads(value)
                assert found == value, name
    finally:
        e2e.set_ring(None)
        await nc.close()
