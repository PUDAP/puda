import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.fixture
def http_server():
    records = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            records.append(
                (
                    self.path,
                    self.headers,
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(self.server.status)
            self.end_headers()
            self.wfile.write(self.server.body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.status, server.body = 200, b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, records
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_http_batches_and_waits_for_confirmed_insert(http_server):
    from subscriber import ClickHouse, Config

    server, records = http_server
    config = Config(
        ["nats://127.0.0.1:14222"],
        f"http://127.0.0.1:{server.server_port}",
        "test",
        "fake-secret",
    )
    client = ClickHouse(config)
    client.write(
        [{"msg_type": "command", "event_ns": 1783417302123456789, "raw_json": '{"x":1}'}, {"msg_type": "command", "event_ns": 2}]
    )
    path, headers, body = records[0]
    assert "fake-secret" not in path and headers["X-ClickHouse-Key"] == "fake-secret"
    assert parse_qs(urlsplit(path).query)["async_insert"] == ["0"]
    assert parse_qs(urlsplit(path).query)["wait_end_of_query"] == ["1"]
    rows = [json.loads(line) for line in body.splitlines()]
    assert rows[0]["event_ns"] == 1783417302123456789 and len(rows) == 2
    server.status, server.body = 500, b"fake-secret payload secret"
    with pytest.raises(RuntimeError) as caught:
        client.write([{"msg_type": "command", "event_ns": 1}])
    assert "fake-secret" not in str(caught.value)
    server.status, server.body = 200, b"Code: 241. secret failed after headers"
    with pytest.raises(RuntimeError):
        client.write([{"msg_type": "command", "event_ns": 1}])


def test_http_redirect_is_not_followed(http_server):
    from subscriber import ClickHouse, Config

    server, records = http_server
    server.status = 302
    with pytest.raises(RuntimeError):
        ClickHouse(
            Config([], f"http://127.0.0.1:{server.server_port}", "test", "secret")
        ).write([{"msg_type": "command"}])
    assert len(records) == 1
