"""Compatibility only: no dotenv, live credentials, broker or database."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [{"cpu": 6, "status": "ok"}, {"status": "ok", "custom": [None, 1]}])
async def test_health_envelope_uses_outer_time_and_inner_labels(monkeypatch, values):
    monkeypatch.setenv("NATS_SERVERS", "nats://127.0.0.1:14222")
    monkeypatch.setenv("REDUCTSTORE_URL", "http://127.0.0.1:18383")
    monkeypatch.setenv("REDUCTSTORE_TOKEN", "test-only")
    with patch("dotenv.load_dotenv", return_value=False):
        module = importlib.import_module("main")
    service = module.LoggerService()
    service.db = SimpleNamespace(write=AsyncMock())
    service._finish = AsyncMock()
    raw = json.dumps({"timestamp": "2026-07-07T09:41:42Z", "data": values}).encode()
    msg = SimpleNamespace(subject="puda.first.tlm.health", data=raw)
    await service._on_telemetry(msg)
    entry, stored_raw, timestamp, labels = service.db.write.await_args.args
    assert timestamp.isoformat() == "2026-07-07T09:41:42+00:00"
    assert stored_raw == raw and labels["status"] == "ok"
    if "cpu" in values:
        assert labels["cpu"] == 6
    service._finish.assert_awaited_once_with(msg, True)


@pytest.mark.asyncio
async def test_finish_never_replies_to_core_requests(monkeypatch):
    monkeypatch.setenv("NATS_SERVERS", "nats://127.0.0.1:14222")
    monkeypatch.setenv("REDUCTSTORE_URL", "http://127.0.0.1:18383")
    monkeypatch.setenv("REDUCTSTORE_TOKEN", "test-only")
    with patch("dotenv.load_dotenv", return_value=False):
        module = importlib.import_module("main")
    service = module.LoggerService()
    ping = SimpleNamespace(reply="_INBOX.cli.1", ack=AsyncMock(), nak=AsyncMock())
    await service._finish(ping, False)
    await service._finish(ping, True)
    ping.ack.assert_not_awaited()
    ping.nak.assert_not_awaited()
    delivery = SimpleNamespace(reply="$JS.ACK.RESPONSE_QUEUE.c.1.1.1.1.0", ack=AsyncMock(), nak=AsyncMock())
    await service._finish(delivery, False)
    delivery.nak.assert_awaited_once()
