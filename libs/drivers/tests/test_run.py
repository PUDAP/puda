"""Tests for opentrons_driver.controllers.run."""

from unittest.mock import patch

import pytest

from opentrons_driver.controllers.run import (
    create_run,
    get_run_status,
    pause_run,
    play_run,
    stop_run,
    wait_for_completion,
)


# ---------------------------------------------------------------------------
# create_run
# ---------------------------------------------------------------------------


class TestCreateRun:
    def test_returns_run_id(self, mock_client, make_response):
        fake_resp = make_response(201, {"data": {"id": "run-abc"}})
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            rid = create_run(mock_client, "proto-1")
        assert rid == "run-abc"

    def test_raises_on_http_error(self, mock_client, make_response):
        fake_resp = make_response(500, text="error")
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            with pytest.raises(RuntimeError, match="Failed to create run"):
                create_run(mock_client, "proto-1")

    def test_raises_when_no_id(self, mock_client, make_response):
        fake_resp = make_response(201, {"data": {}})
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            with pytest.raises(RuntimeError, match="no ID returned"):
                create_run(mock_client, "proto-1")


# ---------------------------------------------------------------------------
# play / pause / stop
# ---------------------------------------------------------------------------


class TestRunActions:
    def test_play_returns_true_on_success(self, mock_client, make_response):
        fake_resp = make_response(200)
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            assert play_run(mock_client, "run-1") is True

    def test_play_returns_false_on_error(self, mock_client, make_response):
        fake_resp = make_response(400)
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            assert play_run(mock_client, "run-1") is False

    def test_pause_returns_true(self, mock_client, make_response):
        fake_resp = make_response(200)
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            assert pause_run(mock_client, "run-1") is True

    def test_stop_returns_true(self, mock_client, make_response):
        fake_resp = make_response(200)
        with patch("opentrons_driver.controllers.run.OT2HttpClient.post", return_value=fake_resp):
            assert stop_run(mock_client, "run-1") is True


# ---------------------------------------------------------------------------
# get_run_status
# ---------------------------------------------------------------------------


class TestGetRunStatus:
    def _run_data(self, status="running"):
        return {
            "data": {
                "id": "run-99",
                "status": status,
                "errors": [],
                "startedAt": "2026-01-01T00:00:00",
                "completedAt": None,
            }
        }

    def test_specific_run_success(self, mock_client, make_response):
        run_resp = make_response(200, self._run_data("succeeded"))
        cmd_resp = make_response(200, {"data": []})
        with patch(
            "opentrons_driver.controllers.run.OT2HttpClient.get",
            side_effect=[run_resp, cmd_resp],
        ):
            result = get_run_status(mock_client, "run-99")
        assert result["status"] == "success"
        assert result["run_status"] == "succeeded"
        assert result["run_id"] == "run-99"

    def test_specific_run_http_error(self, mock_client, make_response):
        fake_resp = make_response(404)
        with patch("opentrons_driver.controllers.run.OT2HttpClient.get", return_value=fake_resp):
            result = get_run_status(mock_client, "run-bad")
        assert result["status"] == "error"

    def test_normalises_none_string(self, mock_client, make_response):
        """run_id="None" should be treated as no run_id → fetch latest."""
        runs_resp = make_response(200, {"data": [self._run_data("idle")["data"]]})
        cmd_resp = make_response(200, {"data": []})
        with patch(
            "opentrons_driver.controllers.run.OT2HttpClient.get",
            side_effect=[runs_resp, cmd_resp],
        ):
            result = get_run_status(mock_client, "None")
        assert result["status"] == "success"

    def test_no_runs_on_robot(self, mock_client, make_response):
        fake_resp = make_response(200, {"data": []})
        with patch("opentrons_driver.controllers.run.OT2HttpClient.get", return_value=fake_resp):
            result = get_run_status(mock_client, None)
        assert result["status"] == "success"
        assert "No runs" in result.get("message", "")


# ---------------------------------------------------------------------------
# wait_for_completion
# ---------------------------------------------------------------------------


class TestWaitForCompletion:
    def _make_status_response(self, run_status: str, make_response):
        return make_response(
            200,
            {
                "data": {
                    "id": "run-w",
                    "status": run_status,
                    "errors": [],
                    "startedAt": None,
                    "completedAt": None,
                }
            },
        )

    def test_returns_immediately_on_terminal_state(self, mock_client, make_response):
        run_resp = self._make_status_response("succeeded", make_response)
        cmd_resp = make_response(200, {"data": []})
        with patch(
            "opentrons_driver.controllers.run.OT2HttpClient.get",
            side_effect=[run_resp, cmd_resp],
        ):
            result = wait_for_completion(mock_client, "run-w", max_wait=30)
        assert result["run_status"] == "succeeded"
        assert result["elapsed_seconds"] == 0

    def test_timeout_when_never_terminal(self, mock_client, make_response):
        run_resp = self._make_status_response("running", make_response)
        cmd_resp = make_response(200, {"data": []})
        with patch(
            "opentrons_driver.controllers.run.OT2HttpClient.get",
            side_effect=[run_resp, cmd_resp] * 50,
        ), patch("opentrons_driver.controllers.run.time.sleep"):
            result = wait_for_completion(
                mock_client, "run-w", max_wait=6, poll_interval=3
            )
        assert result["run_status"] == "timeout"

    def test_failed_run_is_terminal(self, mock_client, make_response):
        run_resp = self._make_status_response("failed", make_response)
        cmd_resp = make_response(200, {"data": []})
        with patch(
            "opentrons_driver.controllers.run.OT2HttpClient.get",
            side_effect=[run_resp, cmd_resp],
        ):
            result = wait_for_completion(mock_client, "run-w", max_wait=30)
        assert result["run_status"] == "failed"
