#!/usr/bin/python3
"""One-shot SSH forced-command helper, stdlib only; never a daemon.

Install root-owned at /usr/local/libexec/puda-native-key-install. Run as the
UID owning the dedicated private dictionary directory, never root.
"""
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile

TARGET = Path('/home/puda/.config/puda/clickhouse-logger-e2ee/dictionary/puda-keys.tsv')
LIMIT = 1024 * 1024


def install(payload, target=TARGET):
    if not payload or len(payload) > LIMIT:
        raise ValueError('Invalid dictionary size')
    seen = set()
    for line in payload.decode('ascii').splitlines():
        kid, encoded = line.split('\t')
        key = bytes.fromhex(encoded)
        if (len(key) != 32 or encoded != key.hex() or kid in seen
                or kid != hashlib.sha256(key).digest()[:4].hex().upper()):
            raise ValueError('Invalid dictionary')
        seen.add(kid)
    target = Path(target)
    info = target.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Dictionary directory must be private and owned')
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.keys-')
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        # Read the exact installed target back, not the input buffer.
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            actual = source.read(LIMIT + 1)
        if actual != payload:
            raise ValueError('Readback mismatch')
        return hashlib.sha256(actual).hexdigest()
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 1:
            raise ValueError('No arguments accepted')
        print(install(sys.stdin.buffer.read(LIMIT + 1)))
    except Exception:
        print('Key install failed (details suppressed)', file=sys.stderr)
        sys.exit(1)
