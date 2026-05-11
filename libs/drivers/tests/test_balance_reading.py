"""Tests for balance_driver.controllers.reading."""

from unittest.mock import patch

import pytest

from balance_driver.controllers.reading import (
    connect_balance,
    diagnose_balance,
    disconnect_balance,
    get_balance_status,
    get_latest_reading,
    monitor_balance,
    read_balance,
    tare_balance,
)
from balance_driver.core.http_client import BalanceBridgeClient


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return BalanceBridgeClient(host="localhost", port=9000)


def _resp(status_code: int, json_data: dict | None = None, text: str = ""):
    from unittest.mock import MagicMock

    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = text
    return r


# ---------------------------------------------------------------------------
# connect_balance
# ---------------------------------------------------------------------------


class TestConnectBalance:
    def test_returns_result_on_success(self, client):
        fake = _resp(200, {"status": "connected", "port": "COM8", "baudrate": 115200})
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = connect_balance(client, port="COM8", baudrate=115200)
        assert result["status"] == "connected"
        assert result["port"] == "COM8"

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="serial error")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to connect"):
                connect_balance(client, port="COM8")

    def test_already_connected_status_is_returned(self, client):
        fake = _resp(200, {"status": "already_connected", "port": "COM8"})
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = connect_balance(client, port="COM8")
        assert result["status"] == "already_connected"


# ---------------------------------------------------------------------------
# disconnect_balance
# ---------------------------------------------------------------------------


class TestDisconnectBalance:
    def test_returns_result_on_success(self, client):
        fake = _resp(200, {"status": "disconnected", "port": "COM8"})
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = disconnect_balance(client, port="COM8")
        assert result["status"] == "disconnected"

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to disconnect"):
                disconnect_balance(client, port="COM8")


# ---------------------------------------------------------------------------
# read_balance
# ---------------------------------------------------------------------------


class TestReadBalance:
    def test_returns_mass_on_success(self, client):
        fake = _resp(200, {"status": "success", "mass_g": 12.345, "mass_mg": 12345.0})
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = read_balance(client, port="COM8")
        assert result["mass_g"] == pytest.approx(12.345)

    def test_raises_on_not_connected(self, client):
        fake = _resp(400, text="Not connected")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to read balance"):
                read_balance(client, port="COM8")


# ---------------------------------------------------------------------------
# get_latest_reading
# ---------------------------------------------------------------------------


class TestGetLatestReading:
    def test_returns_fresh_reading(self, client):
        payload = {
            "status": "success",
            "port": "COM8",
            "mass_g": 5.001,
            "mass_mg": 5001.0,
            "fresh": True,
            "age_seconds": 0.1,
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = get_latest_reading(client, port="COM8")
        assert result["fresh"] is True
        assert result["mass_g"] == pytest.approx(5.001)

    def test_raises_when_not_connected(self, client):
        fake = _resp(400, text="Not connected to COM8")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to get latest reading"):
                get_latest_reading(client, port="COM8")


# ---------------------------------------------------------------------------
# tare_balance
# ---------------------------------------------------------------------------


class TestTareBalance:
    def test_returns_success(self, client):
        fake = _resp(200, {"status": "success", "port": "COM8"})
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = tare_balance(client, port="COM8", wait=0.1)
        assert result["status"] == "success"

    def test_raises_on_http_error(self, client):
        fake = _resp(400, text="Not connected")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to tare balance"):
                tare_balance(client, port="COM8", wait=0.1)


# ---------------------------------------------------------------------------
# get_balance_status
# ---------------------------------------------------------------------------


class TestGetBalanceStatus:
    def test_returns_status(self, client):
        payload = {"connected": True, "background_reader_active": True, "has_data": True}
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = get_balance_status(client, port="COM8")
        assert result["connected"] is True

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="server error")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to get balance status"):
                get_balance_status(client, port="COM8")


# ---------------------------------------------------------------------------
# monitor_balance
# ---------------------------------------------------------------------------


class TestMonitorBalance:
    def test_returns_monitor_data(self, client):
        payload = {
            "port": "COM8",
            "total_messages": 5,
            "readable_messages": 5,
            "diagnosis": "Data looks readable",
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = monitor_balance(client, port="COM8", duration=2)
        assert result["total_messages"] == 5

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to monitor balance"):
                monitor_balance(client, port="COM8", duration=2)


# ---------------------------------------------------------------------------
# diagnose_balance
# ---------------------------------------------------------------------------


class TestDiagnoseBalance:
    def test_returns_best_baudrate(self, client):
        payload = {
            "port": "COM8",
            "best_baudrate": 115200,
            "summary": "Best: 115200 baud",
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = diagnose_balance(client, port="COM8")
        assert result["best_baudrate"] == 115200

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to diagnose balance"):
                diagnose_balance(client, port="COM8")
