"""One private, literal ClickHouse named-collection config for both clients.

No dotenv, credential URLs, insecure TLS, discovery override, or secret SQL.
"""
import ssl
from xml.etree import ElementTree as ET

from native_ingest import read_private
from native_sql import validate_settings

COLLECTION = 'puda_native_nats'


async def quiet_error(_error):
    # nats-py's default callback prints exception text; never log credentials.
    pass


def connect_options(path, server, ca_file=None):
    validate_settings(server, '/unused', COLLECTION)
    raw = read_private(path)
    if '<!DOCTYPE' in raw or '<!ENTITY' in raw:
        raise ValueError('Only literal transport XML is allowed')
    root = ET.fromstring(raw)
    collections = root.find('named_collections')
    if root.tag != 'clickhouse' or len(root) != 1 or collections is None or len(collections) != 1:
        raise ValueError('Expected a dedicated named collection config')
    collection = collections.find(COLLECTION)
    if collection is None or root.attrib or collections.attrib or collection.attrib:
        raise ValueError('Missing native collection')
    allowed = {'nats_url', 'nats_secure', 'nats_ca_file', 'nats_username',
               'nats_password', 'nats_token', 'nats_credential_file',
               'nats_client_cert_file', 'nats_client_key_file'}
    values = {}
    for child in collection:
        if child.tag not in allowed or child.tag in values or len(child) or any(
                k != 'overridable' or v != 'false' for k, v in child.attrib.items()):
            raise ValueError('Unsupported transport option')
        values[child.tag] = child.text or ''
    if values.get('nats_url') != server or values.get('nats_secure') != 'true' or not values.get('nats_ca_file'):
        raise ValueError('TLS endpoint and trusted CA must match')
    user, password = values.get('nats_username'), values.get('nats_password')
    token, credentials = values.get('nats_token'), values.get('nats_credential_file')
    if bool(user) != bool(password) or sum(map(bool, (user, token, credentials))) > 1:
        raise ValueError('Choose one complete NATS authentication method')
    cert, key = values.get('nats_client_cert_file'), values.get('nats_client_key_file')
    if bool(cert) != bool(key):
        raise ValueError('Client certificate and key must be paired')
    context = ssl.create_default_context(cafile=ca_file or values['nats_ca_file'])
    if cert:
        read_private(key)
        context.load_cert_chain(cert, key)
    options = dict(servers=[server], tls=context, allow_reconnect=False,
                   connect_timeout=5, error_cb=quiet_error)
    if user:
        options.update(user=user, password=password)
    if token:
        options['token'] = token
    if credentials:
        read_private(credentials)
        options['user_credentials'] = credentials
    return options
