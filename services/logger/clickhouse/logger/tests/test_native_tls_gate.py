"""The pinned upstream native engine lacks endpoint-name verification."""
import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_tls_install_is_blocked_before_any_side_effect():
    from native_control import install
    args = SimpleNamespace(action='install', server='tls://127.0.0.1:4222',
        url='http://127.0.0.1:8123', keys='/unused', transport='/missing',
        local_ca=None, remote_target=None, remote_key_path=None)
    with pytest.raises(RuntimeError, match='hostname verification'):
        await install(args)
