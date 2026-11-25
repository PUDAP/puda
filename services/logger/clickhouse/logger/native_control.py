"""Explicit opt-in local control plane. No dotenv, data subscription, or worker."""
import argparse
import asyncio
import sys

from native_ingest import bootstrap_keys, read_keys, read_private, provision_consumers
from native_sql import statements, validate_settings


async def install(args):
    import nats
    from urllib.parse import urlsplit
    from storage import Config, ClickHouse
    url = urlsplit(args.url)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password or url.path or url.query or url.fragment:
        raise ValueError('Only explicit loopback ClickHouse URLs are enabled')
    from native_transport import COLLECTION, connect_options, quiet_error
    if args.action == 'install' and args.server.startswith('tls:'):
        # 26.10.2.103 verifies CA chains but accepts wrong endpoint names.
        # No override: re-enable only after the real engine negative test passes.
        raise RuntimeError('Native TLS install blocked: engine hostname verification is not validated')
    transport = getattr(args, 'transport', None)
    remote = getattr(args, 'remote_target', None)
    remote_path = getattr(args, 'remote_key_path', None)
    if bool(remote) != bool(remote_path):
        raise ValueError('Remote target and server dictionary path must be paired')
    collection = COLLECTION if transport else None
    key_path = remote_path or args.keys
    validate_settings(args.server, key_path, collection)  # before side effects
    options = connect_options(transport, args.server, getattr(args, 'local_ca', None)) if transport else dict(
        servers=[args.server], allow_reconnect=False, error_cb=quiet_error)
    publish = None
    if remote:
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', remote):
            raise ValueError('Expected a configured SSH alias')
        from native_remote import publish_keys
        publish = lambda: publish_keys(args.keys, remote)
    keys = read_keys(args.keys)
    if not keys:
        raise ValueError('Provision keys before enabling ingestion')
    db = ClickHouse(Config([args.server], args.url, args.user, read_private(args.password_file).strip()))
    db.check()
    nc = await nats.connect(**options)
    try:
        if args.action == 'sync':
            from native_ingest import sync_keys_once
            await sync_keys_once(nc.jetstream(), db, args.keys, keys, publish=publish)
            return
        if publish:
            await asyncio.to_thread(publish)
        await provision_consumers(nc.jetstream())
        for sql in statements(args.server, key_path, collection):
            await asyncio.to_thread(db.request, sql)
        count = await asyncio.to_thread(db.request, "SELECT count() FROM system.tables WHERE database='puda' AND name LIKE 'native_%' AND engine='NATS'")
        if int(count) != 6:
            raise RuntimeError('Native source verification failed')
    finally:
        await nc.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    bootstrap = sub.add_parser('bootstrap')
    bootstrap.add_argument('--source', required=True)
    bootstrap.add_argument('--keys', required=True)
    for action in ('install', 'sync'):
        command = sub.add_parser(action)
        for flag in ('server','url','user','password-file','keys'):
            command.add_argument('--' + flag, required=True)
        for flag in ('transport', 'local-ca', 'remote-target', 'remote-key-path'):
            command.add_argument('--' + flag)
    args = parser.parse_args()
    try:
        if args.action == 'bootstrap':
            bootstrap_keys(args.source, args.keys)
        else:
            asyncio.run(install(args))
    except Exception:
        print('Native control failed; inspect permissions and configuration (details suppressed)', file=sys.stderr)
        return 1
    print('Native control completed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
