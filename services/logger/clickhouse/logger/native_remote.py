"""Agent-local transfer to an SSH forced-command helper; no secret argv."""
import hashlib
import re
import subprocess
from native_ingest import read_private, read_keys


def publish_keys(path, target):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', target):
        raise ValueError('Expected a configured SSH host alias')
    read_keys(path)
    payload = read_private(path).encode('ascii')
    result = subprocess.run([
        'ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=10', '-o', 'ClearAllForwardings=yes',
        target, '/usr/local/libexec/puda-native-key-install'],
        input=payload, capture_output=True, timeout=30, check=False)
    if result.returncode or result.stdout.strip() != hashlib.sha256(payload).hexdigest().encode():
        raise RuntimeError('Remote dictionary verification failed')
