"""Exercise the production output timing against a real, slow HTTP server.

Run in the logger image, where telegraf and Python 3.11 are available.
No production credentials or database are used.
"""
import http.server
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import unittest


class SlowWriteTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("telegraf"), "requires telegraf")
    def test_write_survives_six_second_response(self):
        template = pathlib.Path(__file__).resolve().parents[1] / "telegraf.conf.template"
        config = tomllib.loads(template.read_text())
        output = config["outputs"]["influxdb_v2"][0]
        accepted = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                time.sleep(6)
                self.send_response(204)
                self.end_headers()
                accepted.set()

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                point = pathlib.Path(tmp) / "point.lp"
                point.write_text("logger_test value=1i\n")
                conf = pathlib.Path(tmp) / "telegraf.conf"
                timeout = output.get("timeout")
                timeout_line = f'timeout = "{timeout}"\n' if timeout else ""
                conf.write_text(
                    '[agent]\n omit_hostname = true\n'
                    f' flush_interval = "{config["agent"]["flush_interval"]}"\n'
                    '[[inputs.file]]\n'
                    f' files = ["{point}"]\n data_format = "influx"\n'
                    '[[outputs.influxdb_v2]]\n'
                    f' urls = ["http://127.0.0.1:{server.server_port}"]\n'
                    ' token = "test-only"\n organization = "test"\n bucket = "test"\n'
                    + timeout_line
                )
                result = subprocess.run(
                    ["telegraf", "--once", "--config", str(conf)],
                    capture_output=True, text=True, timeout=35,
                )
                logs = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, logs)
                self.assertNotIn("E!", logs, logs)
                self.assertTrue(accepted.is_set(), logs)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
