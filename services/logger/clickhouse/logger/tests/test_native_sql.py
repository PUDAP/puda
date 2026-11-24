"""Pure SQL contracts, including compatibility with pre-extraction DDL."""
import hashlib
import importlib.util

import native_ingest


def test_installation_sql_characterization():
    sql = '\n'.join(native_ingest.statements('nats://127.0.0.1:4222'))
    # Timestamp validation has its own differential execution tests.
    sql = sql.replace(native_ingest.timestamp_expression('h'), 'TIMESTAMP_H')
    sql = sql.replace(native_ingest.timestamp_expression('doc'), 'TIMESTAMP_DOC')
    assert hashlib.sha256(sql.encode()).hexdigest() == 'b4bb08b8571981031a7ae312be6adeb11a0700fc1e706d248328b53dad792e1b'


def test_pure_sql_select_api_and_compatibility():
    assert importlib.util.find_spec('native_sql') is not None
    import native_sql
    for name in ('statements', 'command_view', 'telemetry_view', 'last_object',
                 'decrypt_with', 'timestamp_expression', 'DURABLES'):
        assert getattr(native_ingest, name) is getattr(native_sql, name)
    for kind, builder, view, table in (
        ('command', native_sql.command_select, native_sql.command_view, 'command_logs'),
        ('response', native_sql.command_select, native_sql.command_view, 'command_logs'),
        ('telemetry', native_sql.telemetry_select, native_sql.telemetry_view, 'telemetry'),
        ('telemetry_stream', native_sql.telemetry_select, native_sql.telemetry_view, 'telemetry'),
    ):
        assert view('probe', kind) == f'CREATE MATERIALIZED VIEW puda.probe_mv TO puda.{table} AS\n' + builder('puda.probe', kind)
        source = "(SELECT 'test' AS payload, 'subject' AS _subject)"
        assert builder(source, kind).endswith('FROM ' + source)
    assert list(native_sql.key_statements('/private/keys.tsv')) == [
        'CREATE DATABASE IF NOT EXISTS puda_native_secrets',
        "CREATE DICTIONARY puda_native_secrets.keys (kid String, key_hex String)\n        PRIMARY KEY kid SOURCE(FILE(PATH '/private/keys.tsv' FORMAT 'TabSeparated'))\n        LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(0)",
    ]
