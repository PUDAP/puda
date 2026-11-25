import ssl


def test_transport_local_ca_and_literal_nodes(tmp_path):
    from native_transport import connect_options
    from ssl import get_default_verify_paths
    path = tmp_path / 'transport.xml'
    xml = ('<clickhouse><named_collections><puda_native_nats>'
           '<nats_url overridable="false">tls://localhost:4222</nats_url>'
           '<nats_secure overridable="false">true</nats_secure>'
           '<nats_ca_file overridable="false">/remote/ca.pem</nats_ca_file>'
           '</puda_native_nats></named_collections></clickhouse>')
    path.write_text(xml)
    path.chmod(0o600)
    options = connect_options(path, 'tls://localhost:4222', ca_file='/etc/ssl/certs/ca-certificates.crt')
    assert options['tls'].verify_mode == ssl.CERT_REQUIRED
    assert options['tls'].check_hostname
    path.write_text(xml.replace('<puda_native_nats>', '<puda_native_nats from_env="BAD">'))
    with pytest.raises(ValueError):
        connect_options(path, 'tls://localhost:4222', ca_file='/etc/ssl/certs/ca-certificates.crt')
import pytest


def test_shared_transport_rejects_downgrade_and_unsafe_options(tmp_path):
    import native_transport
    path = tmp_path / 'transport.xml'
    path.write_text('<clickhouse><named_collections><puda_native_nats>'
                    '<nats_url>tls://localhost:4222</nats_url>'
                    '<nats_secure>true</nats_secure><nats_ca_file>/missing/ca.pem</nats_ca_file>'
                    '</puda_native_nats></named_collections></clickhouse>')
    path.chmod(0o600)
    with pytest.raises(FileNotFoundError):
        native_transport.connect_options(path, 'tls://localhost:4222')
    with pytest.raises(ValueError):
        native_transport.connect_options(path, 'tls://other:4222')
    path.write_text(path.read_text().replace('<nats_secure>true', '<nats_secure>false'))
    with pytest.raises(ValueError):
        native_transport.connect_options(path, 'tls://localhost:4222')

from native_sql import statements


def test_secure_collection_ddl_has_no_transport_values():
    sql = '\n'.join(statements('tls://pudadev:4222', named_collection='puda_native_nats'))
    assert 'ENGINE=NATS(puda_native_nats)' in sql
    assert 'pudadev' not in sql
    assert 'nats_url=' not in sql
    with pytest.raises(ValueError):
        list(statements('tls://pudadev:4222'))
    with pytest.raises(ValueError):
        list(statements('nats://pudadev:4222', named_collection='puda_native_nats'))
    with pytest.raises(ValueError):
        list(statements('tls://pudadev:4222', named_collection="bad')"))
