"""Tests for balance_driver.cli"""

from unittest.mock import MagicMock, patch

import pytest

from balance_driver.cli import main


def _resp(status_code: int, json_data: dict | None = None, text: str = ""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = text
    return r


def _run(*argv: str) -> int:
    """Run the CLI and return the exit code (captured via SystemExit)."""
    with pytest.raises(SystemExit) as exc_info:
        main(list(argv))
    return exc_info.value.code


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


class TestCLIConnect:
    def test_connect_success(self, capsys):
        bridge_resp = _resp(200, {"status": "running"})
        conn_resp = _resp(200, {"status": "connected", "port": "COM8", "baudrate": 115200, "mode": "arduino"})
        with patch("balance_driver.core.http_client.requests.get", return_value=bridge_resp), \
             patch("balance_driver.core.http_client.requests.post", return_value=conn_resp):
            code = _run("connect", "COM8")
        assert code == 0
        out = capsys.readouterr().out
        assert "COM8" in out

    def test_connect_bridge_unreachable(self, capsys):
        import requests as req
        with patch("balance_driver.core.http_client.requests.get",
                   side_effect=req.exceptions.ConnectionError):
            code = _run("connect", "COM8")
        assert code == 1
        assert "not reachable" in capsys.readouterr().err

    def test_connect_serial_error(self, capsys):
        bridge_resp = _resp(200, {"status": "running"})
        err_resp = _resp(500, text="serial error")
        with patch("balance_driver.core.http_client.requests.get", return_value=bridge_resp), \
             patch("balance_driver.core.http_client.requests.post", return_value=err_resp):
            code = _run("connect", "COM8")
        assert code == 1


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestCLIDisconnect:
    def test_disconnect_success(self, capsys):
        resp = _resp(200, {"status": "disconnected", "message": "Disconnected from COM8"})
        with patch("balance_driver.core.http_client.requests.post", return_value=resp):
            code = _run("disconnect", "COM8")
        assert code == 0
        assert "COM8" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


class TestCLIRead:
    def test_read_success(self, capsys):
        resp = _resp(200, {
            "status": "success", "mass_g": 5.001, "mass_mg": 5001.0,
            "fresh": True, "age_seconds": 0.2, "calibrated": True,
        })
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("read", "COM8")
        assert code == 0
        assert "5.001" in capsys.readouterr().out

    def test_read_no_data_returns_error(self, capsys):
        resp = _resp(200, {"status": "waiting", "message": "no data yet"})
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("read", "COM8", "--retries", "1")
        assert code == 1


# ---------------------------------------------------------------------------
# tare
# ---------------------------------------------------------------------------


class TestCLITare:
    def test_tare_success(self, capsys):
        reading = _resp(200, {"status": "success", "mass_g": 0.001})
        tare = _resp(200, {"status": "success", "port": "COM8"})
        with patch("balance_driver.core.http_client.requests.get", return_value=reading), \
             patch("balance_driver.core.http_client.requests.post", return_value=tare):
            code = _run("tare", "COM8", "--wait", "0.1")
        assert code == 0
        assert "COM8" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestCLIStatus:
    def test_status_connected(self, capsys):
        resp = _resp(200, {
            "connected": True,
            "background_reader_active": True,
            "has_data": True,
            "baudrate": 115200,
            "latest_mass_g": 2.345,
            "data_age_seconds": 0.5,
        })
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("status", "COM8")
        assert code == 0
        out = capsys.readouterr().out
        assert "True" in out

    def test_status_disconnected_returns_1(self, capsys):
        resp = _resp(200, {"connected": False, "has_data": False})
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("status", "COM8")
        assert code == 1


# ---------------------------------------------------------------------------
# calibrate
# ---------------------------------------------------------------------------


class TestCLICalibrate:
    def test_load_default_calibration(self, capsys):
        resp = _resp(200, {"status": "success", "slope": 17450.3, "intercept": -446.6, "enabled": True})
        with patch("balance_driver.core.http_client.requests.post", return_value=resp):
            code = _run("calibrate", "COM8")
        assert code == 0
        out = capsys.readouterr().out
        assert "17450" in out

    def test_get_calibration(self, capsys):
        resp = _resp(200, {
            "slope": 17450.3, "intercept": -446.6,
            "calibrated": True, "source": "csv_upload",
            "formula": "grams = (raw - -446.6) / 17450.3",
        })
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("calibrate", "COM8", "--get")
        assert code == 0
        assert "17450" in capsys.readouterr().out

    def test_set_calibration(self, capsys):
        resp = _resp(200, {"status": "success", "slope": 17000.0, "intercept": 0.0, "enabled": True})
        with patch("balance_driver.core.http_client.requests.post", return_value=resp):
            code = _run("calibrate", "COM8", "--set", "--slope", "17000")
        assert code == 0

    def test_set_without_slope_returns_error(self, capsys):
        code = _run("calibrate", "COM8", "--set")
        assert code == 1
        assert "--slope" in capsys.readouterr().err

    def test_enable_calibration(self, capsys):
        resp = _resp(200, {"status": "success", "enabled": True})
        with patch("balance_driver.core.http_client.requests.post", return_value=resp):
            code = _run("calibrate", "COM8", "--enable")
        assert code == 0

    def test_test_calibration(self, capsys):
        resp = _resp(200, {"raw_value": 1744626.0, "mass_g": 100.0, "mass_mg": 100000.0, "calibration": {}})
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("calibrate", "COM8", "--test", "--raw", "1744626")
        assert code == 0
        assert "100" in capsys.readouterr().out

    def test_test_without_raw_returns_error(self, capsys):
        code = _run("calibrate", "COM8", "--test")
        assert code == 1
        assert "--raw" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------


class TestCLIDiagnose:
    def test_diagnose_success(self, capsys):
        resp = _resp(200, {
            "port": "COM8",
            "best_baudrate": 115200,
            "summary": "Best: 115200 baud",
            "results": [
                {"baudrate": 115200, "readable_count": 5, "mass_found": 10.5,
                 "best": True, "recommended": True, "readable_lines": ["10.5"]},
                {"baudrate": 9600, "readable_count": 0, "mass_found": None,
                 "best": False, "recommended": False, "readable_lines": []},
            ],
        })
        with patch("balance_driver.core.http_client.requests.get", return_value=resp):
            code = _run("diagnose", "COM8")
        assert code == 0
        out = capsys.readouterr().out
        assert "115200" in out
        assert "BEST" in out
