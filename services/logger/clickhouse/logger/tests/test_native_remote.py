import hashlib
import os
import subprocess
import pytest


def test_remote_atomic_helper_and_private_transport(tmp_path, monkeypatch):
    import native_remote
    from native_key_install import install
    from native_ingest import write_keys, read_keys
    local, remote = tmp_path / 'local.tsv', tmp_path / 'remote.tsv'
    tmp_path.chmod(0o700)
    key = os.urandom(32)
    write_keys(local, [key])
    payload = local.read_bytes()
    assert install(payload, remote) == hashlib.sha256(payload).hexdigest()
    assert read_keys(remote) == [key]
    assert remote.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        install(b'BAD\t' + b'0' * 64 + b'\n', remote)
    assert read_keys(remote) == [key]
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        assert kw['input'] == payload
        assert key.hex() not in ' '.join(argv)
        assert 'StrictHostKeyChecking=yes' in argv
        return subprocess.CompletedProcess(argv, 0, (hashlib.sha256(payload).hexdigest()+'\n').encode(), b'')
    monkeypatch.setattr(native_remote.subprocess, 'run', run)
    native_remote.publish_keys(local, 'pudadev1-key-sync')
    assert len(calls) == 1
    with pytest.raises(ValueError):
        native_remote.publish_keys(local, '-oProxyCommand=bad')
    def bad(*a, **kw):
        return subprocess.CompletedProcess(a, 0, b'wrong', b'fake secret')
    monkeypatch.setattr(native_remote.subprocess, 'run', bad)
    with pytest.raises(RuntimeError, match='verification failed'):
        native_remote.publish_keys(local, 'pudadev1-key-sync')
