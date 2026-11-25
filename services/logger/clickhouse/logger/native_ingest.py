"""Opt-in native ingestion DDL/control plane. Never consumes data messages."""
import hashlib
import os
from pathlib import Path
import tempfile

from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, RetentionPolicy
from nats.js.errors import NotFoundError

# Compatibility exports: existing operators/tests may import these here.
from native_sql import (
    DURABLES, statements, command_view, telemetry_view, last_object,
    decrypt_with, timestamp_expression, command_select, telemetry_select,
    key_statements, validate_settings,
)


def write_keys(path, keys):
    """Atomically publish a private dictionary file; no key enters SQL."""
    path = Path(path)
    rows = {}
    for key in keys:
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError('Expected AES-256 keys')
        kid = hashlib.sha256(key).digest()[:4].hex().upper()
        if kid in rows and rows[kid] != key.hex():
            raise ValueError('Key ID collision')
        rows[kid] = key.hex()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.keys-')
    try:
        with os.fdopen(fd, 'w') as output:
            for kid, key in rows.items():
                output.write(f'{kid}\t{key}\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_private(path):
    import stat
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ValueError('Key input must be a private owner-only regular file')
        return source.read()


def read_keys(path):
    keys = []
    for line in read_private(path).splitlines():
        kid, encoded = line.split('\t')
        key = bytes.fromhex(encoded)
        if len(key) != 32 or kid != hashlib.sha256(key).digest()[:4].hex().upper():
            raise ValueError('Invalid key dictionary')
        keys.append(key)
    return keys


def bootstrap_keys(source, target):
    import base64
    keys = read_keys(target) if Path(target).exists() else []
    fields = dict(line.split('=',1) for line in read_private(source).splitlines()
                  if line and not line.startswith('#') and '=' in line)
    if not fields.get('encrypt'):
        raise ValueError('Bootstrap requires an encrypt key')
    keys += [base64.b64decode(fields[name], altchars=b'-_', validate=True)
             for name in ('encrypt','previous') if fields.get(name)]
    write_keys(target, keys)


async def sync_keys_once(js, db, path, trusted_keys, publish=None):
    """Read only encrypted KV control data; retain historical replay keys.

    Caller keeps the returned keys for the next poll. A failed reload is fatal;
    the previous dictionary snapshot remains active until a successful reload.
    """
    import asyncio
    import base64
    import json
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        kv = await js.key_value('E2E_KEYRING')
        frame = (await kv.get('current')).value
        if len(frame) < 34 or frame[:2] != b'\xe2\x01':
            raise ValueError
        key = next(k for k in trusted_keys if hashlib.sha256(k).digest()[:4] == frame[2:6])
        record = json.loads(AESGCM(key).decrypt(frame[6:18], frame[18:], b'kv:E2E_KEYRING:current'))
        new = [base64.b64decode(record[field], altchars=b'-_', validate=True) for field in ('new_key','old_key')]
        if record['encrypt_kid'].lower() not in [hashlib.sha256(k).digest()[:4].hex() for k in new]:
            raise ValueError
        keys = list(dict.fromkeys([*trusted_keys, *new]))
        write_keys(path, keys)
        if publish:
            await asyncio.to_thread(publish)
        await asyncio.to_thread(db.request, 'SYSTEM RELOAD DICTIONARY puda_native_secrets.keys')
        # Read back only cardinality, never key bytes (including in query text).
        count = await asyncio.to_thread(db.request, 'SELECT count() FROM puda_native_secrets.keys')
        if int(count) != len(keys):
            raise ValueError
        return keys
    except Exception:
        raise RuntimeError('Native key sync failed; existing keys retained') from None


async def provision_consumers(js):
    """Only additive, separate logger pull durables. Never changes streams."""
    for stream, durable in DURABLES.items():
        info = await js.stream_info(stream)
        if info.config.retention not in (RetentionPolicy.LIMITS, RetentionPolicy.INTEREST):
            raise ValueError('Native logging refuses WorkQueue retention')
        subject = 'puda.*.cmd.response.' + stream.removeprefix('RESPONSE_').lower()
        try:
            existing = await js.consumer_info(stream, durable)
        except NotFoundError:
            await js.add_consumer(stream, config=ConsumerConfig(
                durable_name=durable, filter_subject=subject,
                deliver_policy=DeliverPolicy.ALL, ack_policy=AckPolicy.EXPLICIT,
                ack_wait=2, max_deliver=-1, max_ack_pending=1))
            existing = await js.consumer_info(stream, durable)
        c = existing.config
        if (c.deliver_subject or c.deliver_group or c.filter_subject != subject or c.filter_subjects
                or c.ack_policy != AckPolicy.EXPLICIT or c.max_deliver != -1
                or c.max_ack_pending != 1 or c.ack_wait != 2
                or c.deliver_policy != DeliverPolicy.ALL):
            raise ValueError('Existing native consumer is incompatible')


