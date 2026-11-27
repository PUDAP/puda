"""Remote update request handling (no broker)."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from puda.edge_nats_client import EdgeNatsClient
from puda.edge_updater import EdgeUpdater


def _handle(payload: bytes) -> list[dict]:
    edge = EdgeNatsClient(["nats://localhost:4222"], "test-1")
    publish = AsyncMock()
    edge.nc = SimpleNamespace(publish=publish)  # type: ignore[assignment]
    edge.publish_log = AsyncMock()
    updater = EdgeUpdater(edge)
    msg = SimpleNamespace(subject=edge.update, data=payload)
    asyncio.run(updater._handle_message(msg))
    return [json.loads(call.kwargs["payload"]) for call in publish.call_args_list]


def test_malformed_update_request_is_answered():
    # §14: exactly one response, so the CLI fails fast instead of timing out.
    request = {
        "header": {"protocol_version": "2.0", "message_type": "command", "user_id": "u", "username": "u",
                   "machine_id": "test-1", "run_id": "r-1", "timestamp": "2026-01-01T00:00:00Z"},
        "command": {"name": "update", "params": {"source_type": "git"}, "step_number": 0, "machine_id": "test-1"},
    }
    (response,) = _handle(json.dumps(request).encode())
    assert response["header"]["run_id"] == "r-1"
    assert response["header"]["message_type"] == "response"
    assert response["response"]["code"] == "EXECUTION_ERROR"
    assert "Invalid command envelope" in response["response"]["message"]


def test_uncorrelatable_update_request_is_dropped():
    assert _handle(b"not json") == []
