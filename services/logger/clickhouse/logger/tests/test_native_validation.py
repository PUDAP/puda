"""SQL parity tests complement end-to-end delivery tests."""
import json
import os
import pytest
from puda import e2e
import native_ingest
import native_sql
from storage import to_row
from test_integration import services
from test_logger import command

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_NATIVE_INTEGRATION') != '1', reason='requires isolated native services')]


def test_native_sql_rejects_invalid_wire(services, tmp_path):
    config, db = services
    key = os.urandom(32)
    e2e.set_ring(e2e.Ring(key))
    path = tmp_path / 'user_files' / 'puda-keys.tsv'
    native_ingest.write_keys(path, [key])
    for sql in native_sql.key_statements(path):
        db.request(sql)
    cases = [('puda.robot.tlm.health', raw) for raw in
        [b'[]', b'{"x":1e999}', b'{"x":NaN}', b'{"x":"\\ud800"}', b'\xff', b'{}garbage']]
    for field, value in [('step', 2**63), ('step', -(2**63)-1),
                         ('timestamp','2026-02-30T12:00:00Z'), ('timestamp','2600-01-01T00:00:00Z')]:
        bad = command()
        if field == 'step':
            bad['command']['step_number'] = value
        else:
            bad['header']['timestamp'] = value
        cases.append(('puda.robot.cmd.response.queue', json.dumps(bad).encode()))
    try:
        for subject, raw in cases:
            with pytest.raises((ValueError, UnicodeError)):
                to_row(subject, raw)
            frame = e2e.seal(subject, raw)
            source = f"(SELECT unhex('{frame.hex()}') AS payload, '{subject}' AS _subject)"
            select = native_sql.command_select(source, 'response') if '.cmd.' in subject else native_sql.telemetry_select(source, 'telemetry')
            with pytest.raises(RuntimeError, match='ClickHouse request failed'):
                db.request(select)
        duplicate = json.dumps(command()).replace('"machine_id": "robot"', '"machine_id":"wrong","machine_id":"robot"').encode()
        for subject, raw in [('puda.robot.cmd.response.queue', duplicate),
                             ('puda.robot.cmd.response.queue', json.dumps(command()).encode()),
                             ('puda.robot.tlm.health', b'{"cpu":1}')]:
            frame = e2e.seal(subject, raw)
            source = f"(SELECT unhex('{frame.hex()}') AS payload, '{subject}' AS _subject)"
            select = native_sql.command_select(source, 'response') if '.cmd.' in subject else native_sql.telemetry_select(source, 'telemetry')
            actual = json.loads(db.request(select + ' FORMAT JSONEachRow'))
            assert actual['raw_json'] == raw.decode()
            assert actual['machine_id'] == to_row(subject,raw)['machine_id']
    finally:
        e2e.set_ring(None)


def test_timestamp_calendar_clock_and_bounds_parity(services):
    from storage import timestamp_ns
    _, db = services
    invalid = [
        '2026-01-01T23:60:00Z', '2026-00-01T12:00:00Z', '2026-01-00T12:00:00Z',
        '2026-13-01T12:00:00Z', '2026-01-32T12:00:00Z', '2026-04-31T12:00:00Z',
        '2026-02-29T12:00:00Z', '2100-02-29T12:00:00Z', '2026-01-01T24:01:00Z',
        '2026-01-01T00:00:60Z', '2026-01-01T00:00:00+24:00', '2026-01-01T00:00:00+00:60',
        '1969-12-31T23:59:59.999999999Z', '1970-01-01T00:00:00+00:01',
        '2262-04-11T23:47:16.854775808Z', '2262-04-12T00:47:16.854775808+01:00',
        '2600-01-01T00:00:00Z', '3000-01-01T00:00:00Z', '9999-12-31T23:59:59Z',
    ]
    valid = [
        '1970-01-01T00:00:00Z', '1969-12-31T23:00:00-01:00',
        '1970-01-01T00:00:00.000000001Z', '2000-02-29T12:00:00Z',
        '2024-02-29T23:59:59.123456789+23:59', '2024-02-29T23:59:59.123456789-23:59',
        '2026-07-07T11:41:42.123456789+02:00', '2026-04-30T23:59:59.1Z',
        '2262-04-11T23:47:16.854775807Z', '2262-04-12T00:47:16.854775807+01:00',
    ]
    expression = native_sql.timestamp_expression('doc')
    accepted = []
    for value in invalid:
        with pytest.raises(ValueError):
            timestamp_ns(value)
        doc = json.dumps({'timestamp': value}).encode().hex()
        try:
            db.request(f"SELECT {expression} FROM (SELECT unhex('{doc}') AS doc)")
        except RuntimeError:
            continue
        accepted.append(value)
    assert not accepted, f'SQL accepted invalid timestamps: {accepted}'
    for value in valid:
        doc = json.dumps({'timestamp': value}).encode().hex()
        actual = int(db.request(f"SELECT {expression} FROM (SELECT unhex('{doc}') AS doc)"))
        assert actual == timestamp_ns(value), value
