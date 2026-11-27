"""Conformance tests against the shared Edge Protocol 1.0 artifacts.

The Go CLI runs the same checks (apps/cli/internal/nats/edge-protocol-spec_test.go)
against docs/edge-protocol/v1.0, so a change that makes either side drift from the
spec fails a test.
"""

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jsonschema
import pytest
from pydantic import ValidationError

from puda import PROTOCOL_VERSION, e2e
from puda.command import command
from puda.command_processor import CommandProcessor, _error, _ok
from puda.command_service import CommandService
from puda.edge_nats_client import EdgeNatsClient
from puda.edge_runner import EdgeRunner
from puda.host_addresses import HostAddresses
from puda.models import CommandRequest, CommandResponseCode, NATSMessage

SPEC = Path(__file__).resolve().parents[3] / "docs" / "edge-protocol" / "v1.0"
VECTORS = json.loads((SPEC / "vectors" / "e2e-vectors.json").read_text())


def schema(name: str) -> dict:
    return json.loads((SPEC / "schemas" / f"{name}.schema.json").read_text())


def validate(name: str, payload) -> None:
    jsonschema.Draft202012Validator(schema(name)).validate(payload)


def examples(*patterns: str) -> list[Path]:
    paths = [path for pattern in patterns for path in sorted((SPEC / "examples").glob(pattern))]
    assert paths, f"no spec examples match {patterns}"
    return paths


def require_preserved(label: str, original: dict, decoded: dict, fields) -> None:
    """A spec field the SDK drops or changes on decode is data the peer sent and lost."""
    for field in fields:
        want = original.get(field)
        if want is None or want == {}:
            continue
        assert decoded.get(field) == want, f"{label}: field {field!r} changed after SDK decode"


@pytest.mark.parametrize("vector", VECTORS["positive"], ids=lambda v: v["name"])
def test_spec_vector_seals_byte_identical_and_opens(vector):
    ring = e2e.Ring(encrypt=base64.b64decode(vector["key_b64"]))
    frame = bytes.fromhex(vector["frame_hex"])
    plaintext = vector["plaintext_utf8"].encode()
    assert e2e._seal(ring, vector["aad"], plaintext, nonce=bytes.fromhex(vector["nonce_hex"])) == frame
    assert e2e._open_payload(ring, vector["aad"], frame) == plaintext


@pytest.mark.parametrize("vector", VECTORS["negative"], ids=lambda v: v["name"])
def test_spec_negative_vector_outcome(vector):
    keys = [base64.b64decode(k) for k in vector["keys_b64"]]
    ring = e2e.Ring(encrypt=keys[0], previous=keys[1] if len(keys) > 1 else None) if keys else None
    data = bytes.fromhex(vector["frame_hex"])
    try:
        plain = e2e._open_payload(ring, vector["aad"], data)
    except e2e.E2EError:
        outcome = "reject"
    else:
        outcome = "accept_as_plaintext" if ring is None and plain == data else "accept"
    assert outcome == vector["expect"]


@pytest.mark.parametrize(
    "path", examples("command-*.json", "response-*.json", "update-*.json"), ids=lambda p: p.name
)
def test_spec_envelope_example_round_trips(path):
    original = json.loads(path.read_text())
    if original["header"]["protocol_version"].split(".")[0] != "1":
        # The edge's refusal echoes the foreign version; the SDK must not accept it.
        with pytest.raises(ValidationError, match="unsupported protocol version"):
            NATSMessage.model_validate(original)
        return
    decoded = json.loads(NATSMessage.model_validate(original).model_dump_json())
    validate("nats-message", decoded)
    envelope = schema("nats-message")["properties"]
    for section in ("header", "command", "response"):
        if original.get(section):
            require_preserved(
                f"{path.name} {section}", original[section], decoded[section], envelope[section]["properties"]
            )


def test_unknown_response_code_from_a_newer_minor_is_accepted():
    # §2: a minor may add response codes; a 1.0 client reads them as errors.
    original = json.loads((SPEC / "examples" / "response-queue-unknown-command.json").read_text())
    original["response"]["code"] = "SOME_NEW_CODE"
    message = NATSMessage.model_validate(original)
    assert message.response is not None and message.response.code == "SOME_NEW_CODE"
    validate("nats-message", json.loads(message.model_dump_json()))


def test_sdk_command_payload_matches_spec():
    service = object.__new__(CommandService)
    for run_id in ("22222222-2222-4333-8444-555555555555", ""):
        request = CommandRequest(name="echo", params={"message": "hi"}, step_number=1, machine_id="proto-test")
        message = service._build_command_payload(request, "proto-test", run_id, "user", "puda")
        validate("nats-message", json.loads(message.model_dump_json()))


@pytest.mark.parametrize(
    "response",
    [_ok(), _error(CommandResponseCode.EXECUTION_LOCKED, "busy", {"running": "echo"})],
    ids=["success", "error"],
)
def test_sdk_response_to_spec_command_matches_spec(response):
    processor = SimpleNamespace(_client=SimpleNamespace(encryption=e2e.Context()))
    msg = SimpleNamespace(subject="puda.proto-test.cmd.queue", data=(SPEC / "examples" / "command-queue.json").read_bytes())
    text = CommandProcessor._response_text(processor, msg, response)  # type: ignore[arg-type]
    assert text is not None
    validate("nats-message", json.loads(text))


def test_sdk_pong_matches_spec(tmp_path):
    key_file = tmp_path / "e2e.key"
    key_file.write_text("encrypt=" + base64.b64encode(bytes([0x11]) * 32).decode() + "\n")
    with patch("puda.edge_nats_client.discover_host_addresses", return_value=HostAddresses()):
        for kwargs in ({}, {"e2e_key_file": str(key_file)}):
            client = EdgeNatsClient(["nats://localhost:4222"], "proto-test", "Spec test edge", **kwargs)
            client.set_runtime_status_handler(lambda: "idle")
            validate("pong", asyncio.run(client._pong_payload()))


class _Driver:
    @command
    def move_to(self, x_mm: float, y_mm: float = 0.0) -> dict:
        """Move the head."""
        return {}

    def pause(self) -> None:
        pass


def test_sdk_catalog_matches_spec():
    client = EdgeNatsClient(["nats://localhost:4222"], "proto-test")
    client.publish_commands = AsyncMock()  # type: ignore[method-assign]
    asyncio.run(EdgeRunner(client, _Driver())._publish_commands())
    (payload,), _ = client.publish_commands.call_args
    validate("machine-commands", payload)
    assert payload["protocol_version"] == PROTOCOL_VERSION  # §11.1: KV values outlive their writer


def test_sdk_state_value_matches_spec():
    client = EdgeNatsClient(["nats://localhost:4222"], "proto-test")
    client.kv_state = SimpleNamespace(put=AsyncMock())  # type: ignore[assignment]
    client.set_state_handler(lambda: {"homed": True})
    asyncio.run(client.publish_state({"state": "idle", "run_id": None}))
    stored = json.loads(client.kv_state.put.call_args.args[1])
    validate("machine-state", stored)
    assert stored["protocol_version"] == PROTOCOL_VERSION  # §10
