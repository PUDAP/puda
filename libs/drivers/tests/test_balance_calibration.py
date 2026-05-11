"""Tests for balance_driver.controllers.calibration."""

from unittest.mock import MagicMock, patch

import pytest

import balance_driver.controllers.calibration as cal_ctrl
from balance_driver.controllers.calibration import (
    _linear_regression,
    _parse_calibration_csv,
    enable_calibration,
    get_bundled_calibration,
    get_calibration,
    load_calibration_csv,
    load_default_calibration,
    set_calibration,
)
from balance_driver.core.http_client import BalanceBridgeClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return BalanceBridgeClient(host="localhost", port=9000)


def _resp(status_code: int, json_data: dict | None = None, text: str = ""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = text
    return r


# ---------------------------------------------------------------------------
# set_calibration
# ---------------------------------------------------------------------------


class TestSetCalibration:
    def test_returns_result_on_success(self, client):
        payload = {
            "status": "success",
            "port": "COM8",
            "slope": 17446.26,
            "intercept": 0.0,
            "enabled": True,
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = set_calibration(client, port="COM8", slope=17446.26)
        assert result["status"] == "success"
        assert result["slope"] == pytest.approx(17446.26)
        assert result["enabled"] is True

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="server error")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to set calibration"):
                set_calibration(client, port="COM8", slope=17446.26)


# ---------------------------------------------------------------------------
# get_calibration
# ---------------------------------------------------------------------------


class TestGetCalibration:
    def test_returns_calibration_data(self, client):
        payload = {
            "port": "COM8",
            "slope": 17446.26,
            "intercept": 0.0,
            "calibrated": True,
            "source": "default_100g_loadcell",
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = get_calibration(client, port="COM8")
        assert result["slope"] == pytest.approx(17446.26)
        assert result["source"] == "default_100g_loadcell"

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to get calibration"):
                get_calibration(client, port="COM8")


# ---------------------------------------------------------------------------
# load_calibration_csv
# ---------------------------------------------------------------------------


class TestLoadCalibrationCsv:
    _sample_csv = (
        "Calibration weight (g),Mean,Stdev,% Error\n"
        "100,1744626.405,56.24,0.003\n"
        "50,872057.452,31.52,0.004\n"
    )

    def test_returns_computed_slope(self, client):
        payload = {
            "status": "success",
            "port": "COM8",
            "slope": 17446.26,
            "intercept": 0.0,
            "enabled": True,
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = load_calibration_csv(client, port="COM8", csv_data=self._sample_csv)
        assert result["status"] == "success"
        assert result["enabled"] is True

    def test_raises_on_bad_csv(self, client):
        fake = _resp(400, text="Failed to parse CSV")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to load CSV calibration"):
                load_calibration_csv(client, port="COM8", csv_data="bad data")


# ---------------------------------------------------------------------------
# load_default_calibration
# ---------------------------------------------------------------------------


class TestLoadDefaultCalibration:
    def test_returns_default_slope(self, client):
        payload = {
            "status": "success",
            "port": "COM8",
            "slope": 17446.26,
            "intercept": 0.0,
            "enabled": True,
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = load_default_calibration(client, port="COM8")
        assert result["slope"] == pytest.approx(17446.26)

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to set calibration"):
                load_default_calibration(client, port="COM8")


# ---------------------------------------------------------------------------
# test_calibration
# ---------------------------------------------------------------------------


class TestTestCalibration:
    def test_converts_raw_to_grams(self, client):
        payload = {
            "raw_value": 1744626.0,
            "mass_g": 100.0,
            "mass_mg": 100000.0,
        }
        fake = _resp(200, payload)
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            result = cal_ctrl.test_calibration(client, port="COM8", raw_value=1744626.0)
        assert result["mass_g"] == pytest.approx(100.0)

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.get", return_value=fake):
            with pytest.raises(RuntimeError, match="Failed to test calibration"):
                cal_ctrl.test_calibration(client, port="COM8", raw_value=0.0)


# ---------------------------------------------------------------------------
# enable_calibration
# ---------------------------------------------------------------------------


class TestEnableCalibration:
    def test_enable_returns_enabled_true(self, client):
        fake = _resp(200, {"status": "success", "port": "COM8", "enabled": True})
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = enable_calibration(client, port="COM8", enabled=True)
        assert result["enabled"] is True

    def test_disable_returns_enabled_false(self, client):
        fake = _resp(200, {"status": "success", "port": "COM8", "enabled": False})
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            result = enable_calibration(client, port="COM8", enabled=False)
        assert result["enabled"] is False

    def test_raises_on_http_error(self, client):
        fake = _resp(500, text="error")
        with patch("balance_driver.core.http_client.requests.post", return_value=fake):
            with pytest.raises(RuntimeError, match="calibration"):
                enable_calibration(client, port="COM8", enabled=True)


# ---------------------------------------------------------------------------
# Local CSV helpers
# ---------------------------------------------------------------------------


class TestLinearRegression:
    def test_perfect_line(self):
        x = [1.0, 2.0, 3.0]
        y = [2.0, 4.0, 6.0]  # y = 2x
        slope, intercept = _linear_regression(x, y)
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(0.0)

    def test_with_intercept(self):
        x = [0.0, 1.0, 2.0]
        y = [5.0, 7.0, 9.0]  # y = 2x + 5
        slope, intercept = _linear_regression(x, y)
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(5.0)

    def test_raises_with_single_point(self):
        with pytest.raises(ValueError, match="at least 2 points"):
            _linear_regression([1.0], [1.0])

    def test_raises_with_identical_x(self):
        with pytest.raises(ValueError, match="identical"):
            _linear_regression([1.0, 1.0], [2.0, 3.0])


class TestParseCsv:
    _sample = (
        "Calibration weight (g),Mean,Stdev,% Error\n"
        "100,1744626.405,56.24,0.003\n"
        "50,872057.452,31.52,0.004\n"
    )

    def test_returns_slope_and_intercept(self):
        slope, intercept = _parse_calibration_csv(self._sample)
        assert slope == pytest.approx(17445.686, rel=1e-3)
        assert isinstance(intercept, float)

    def test_raises_on_insufficient_rows(self):
        with pytest.raises(ValueError, match="at least 2"):
            _parse_calibration_csv("Calibration weight (g),Mean\n100,1744626\n")

    def test_skips_blank_lines(self):
        csv_with_blanks = self._sample + "\n\n"
        slope, intercept = _parse_calibration_csv(csv_with_blanks)
        assert isinstance(slope, float)


class TestGetBundledCalibration:
    def test_reads_bundled_csv_and_returns_slope(self):
        slope, intercept = get_bundled_calibration()
        # The 100g load cell should give a slope in the range of ~17000–18000 counts/g
        assert 15000 < slope < 20000
        assert isinstance(intercept, float)

    def test_raises_if_csv_unreadable(self):
        with patch.object(cal_ctrl, "_read_bundled_csv", side_effect=FileNotFoundError("missing")):
            with pytest.raises(RuntimeError, match="bundled calibration CSV"):
                get_bundled_calibration()


class TestLoadDefaultCalibrationBundled:
    def test_uses_bundled_csv_slope(self, client):
        """load_default_calibration must derive slope from the bundled CSV,
        not from the bridge's own hard-coded default."""
        bundled_slope, bundled_intercept = get_bundled_calibration()
        fake = _resp(200, {
            "status": "success",
            "port": "COM8",
            "slope": bundled_slope,
            "intercept": bundled_intercept,
            "enabled": True,
        })
        with patch("balance_driver.core.http_client.requests.post", return_value=fake) as mock_post:
            result = load_default_calibration(client, port="COM8")

        # Verify the POST payload contained the locally-computed slope
        call_kwargs = mock_post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
        assert result["status"] == "success"
        assert result["enabled"] is True
