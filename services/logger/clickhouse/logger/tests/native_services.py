"""Disposable native services: explicit binaries, random loopback ports, no .env."""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

from storage import ClickHouse, Config


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def native_services(root, temp, tls=None):
    clickhouse = Path(os.environ["CLICKHOUSE_TEST_BINARY"]).resolve(strict=True)
    nats = Path(os.environ["NATS_TEST_BINARY"]).resolve(strict=True)
    http, native, broker = free_port(), free_port(), free_port()
    password = secrets.token_hex(32)
    (temp / "users.xml").write_text(f'''<clickhouse>
<profiles><default><max_threads>2</max_threads></default></profiles>
<users><test><password>{password}</password><networks><ip>127.0.0.1</ip></networks><profile>default</profile><quota>default</quota><access_management>1</access_management><named_collection_control>1</named_collection_control></test></users>
<quotas><default><interval><duration>3600</duration><queries>0</queries><errors>0</errors><result_rows>0</result_rows><read_rows>0</read_rows><execution_time>0</execution_time></interval></default></quotas>
</clickhouse>''')
    (temp / "config.xml").write_text(f'''<clickhouse>
<logger><level>warning</level><log>{temp}/server.log</log><errorlog>{temp}/error.log</errorlog></logger>
<path>{temp}/data/</path><tmp_path>{temp}/tmp/</tmp_path><user_files_path>{temp}/user_files/</user_files_path>
<users_config>{temp}/users.xml</users_config><access_control_path>{temp}/access/</access_control_path><listen_host>127.0.0.1</listen_host>
<http_port>{http}</http_port><tcp_port>{native}</tcp_port>
<query_log><database>system</database><table>query_log</table><flush_interval_milliseconds>100</flush_interval_milliseconds></query_log>
<background_schedule_pool_size>16</background_schedule_pool_size>
<background_message_broker_schedule_pool_size>8</background_message_broker_schedule_pool_size>
<background_distributed_schedule_pool_size>8</background_distributed_schedule_pool_size>
</clickhouse>''')
    scheme = 'nats'
    broker_args = [str(nats), '-a', '127.0.0.1', '-p', str(broker), '-js', '-sd', str(temp / 'nats')]
    if tls:
        from native_tls import certificates
        certificates(temp, bad_name=tls == 'bad-name')
        certificates(temp, prefix='wrong-')
        scheme = 'tls'
        ca = temp / ('wrong-ca.pem' if tls == 'bad-ca' else 'ca.pem')
        xml = ('<clickhouse><named_collections><puda_native_nats>'
               f'<nats_url overridable="false">tls://127.0.0.1:{broker}</nats_url>'
               '<nats_secure overridable="false">true</nats_secure>'
               f'<nats_ca_file overridable="false">{ca}</nats_ca_file>'
               '</puda_native_nats></named_collections></clickhouse>')
        (temp / 'transport.xml').write_text(xml)
        (temp / 'transport.xml').chmod(0o600)
        config_dir = temp / 'config.d'
        config_dir.mkdir()
        (config_dir / 'transport.xml').write_text(xml)
        (temp / 'nats.conf').write_text(
            f'listen: "127.0.0.1:{broker}"\njetstream {{ store_dir: "{temp}/nats" }}\n'
            f'tls {{ cert_file: "{temp}/cert.pem", key_file: "{temp}/key.pem" }}\n')
        broker_args = [str(nats), '-c', str(temp / 'nats.conf')]
    processes = []
    try:
        with (temp / "console.log").open("wb") as output:
            processes.append(subprocess.Popen([str(clickhouse), "server", "--config-file=" + str(temp / "config.xml")], stdout=output, stderr=output))
            processes.append(subprocess.Popen(broker_args, stdout=output, stderr=output))
        config = Config([f"{scheme}://127.0.0.1:{broker}"], f"http://127.0.0.1:{http}", "test", password, batch_interval=0.05)
        db = ClickHouse(config)
        deadline = time.monotonic() + 60
        while True:
            try:
                version = db.request("SELECT version()").decode().strip()
                break
            except RuntimeError:
                if any(p.poll() is not None for p in processes) or time.monotonic() > deadline:
                    raise RuntimeError("Disposable native server did not start; inspect test console.log") from None
                time.sleep(0.2)
        for path in sorted((root / "server/initdb").glob("*.sql")):
            for sql in path.read_text().split(";"):
                if sql.strip():
                    db.request(sql)
        db.check()
        print("Native ClickHouse", version, ";", subprocess.check_output([str(nats), "--version"], text=True).strip())
        yield config, db
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
