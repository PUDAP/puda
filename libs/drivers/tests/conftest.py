"""Shared pytest fixtures for opentrons-driver tests."""

from unittest.mock import MagicMock

import pytest

from opentrons_driver.core.http_client import OT2HttpClient


def _make_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Build a fake requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or ""
    resp.json.return_value = json_data or {}
    return resp


@pytest.fixture
def mock_client(monkeypatch):
    """Return an OT2HttpClient whose HTTP calls are intercepted by monkeypatching."""
    client = OT2HttpClient(robot_ip="192.168.1.1")
    return client


@pytest.fixture
def make_response():
    """Fixture that exposes the _make_response helper to tests."""
    return _make_response
