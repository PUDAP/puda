"""Frame tests shared with the Go CLI codec."""

from __future__ import annotations

import pytest

from puda import e2e
from puda.e2e import Ring

KEY = bytes([0x11]) * 32
NONCE = bytes([0x22]) * 12
SUBJECT = "puda.test.cmd.ping"
PLAIN = b"ping"


@pytest.fixture(autouse=True)
def _reset_ring():
    e2e.reset()
    yield
    e2e.reset()


def test_passthrough_without_key():
    assert e2e.seal(SUBJECT, PLAIN) == PLAIN
    assert e2e.open_payload(SUBJECT, PLAIN) == PLAIN


def test_round_trip_and_rejects():
    e2e.set_ring(Ring(encrypt=KEY))
    frame = e2e.seal(SUBJECT, PLAIN, nonce=NONCE)
    assert frame[:2] == bytes([0xE2, 0x01])
    assert e2e.open_payload(SUBJECT, frame) == PLAIN
    with pytest.raises(e2e.E2EError, match="plaintext"):
        e2e.open_payload(SUBJECT, PLAIN)
    flipped = bytearray(frame)
    flipped[-1] ^= 0x01
    with pytest.raises(e2e.E2EError, match="failed to open"):
        e2e.open_payload(SUBJECT, bytes(flipped))
    with pytest.raises(e2e.E2EError, match="failed to open"):
        e2e.open_payload("puda.other.cmd.ping", frame)


def test_previous_key_opens_until_cleared():
    old = bytes([0x33]) * 32
    e2e.set_ring(Ring(encrypt=old))
    frame = e2e.seal(SUBJECT, PLAIN, nonce=NONCE)
    e2e.set_ring(Ring(encrypt=KEY, previous=old))
    assert e2e.open_payload(SUBJECT, frame) == PLAIN
    e2e.set_ring(Ring(encrypt=KEY))
    with pytest.raises(e2e.E2EError, match="unknown key id"):
        e2e.open_payload(SUBJECT, frame)


def test_frame_without_key_reports_encryption():
    e2e.set_ring(Ring(encrypt=KEY))
    frame = e2e.seal(SUBJECT, PLAIN, nonce=NONCE)
    e2e.set_ring(None)
    with pytest.raises(e2e.E2EError, match="encryption enabled"):
        e2e.open_payload(SUBJECT, frame)


def test_tls_url_requires_ca(monkeypatch):
    monkeypatch.delenv("PUDA_NATS_CA", raising=False)
    with pytest.raises(e2e.E2EError, match="ca_file is required"):
        e2e.connect_kwargs(["tls://127.0.0.1:4222"])
    assert e2e.connect_kwargs(["nats://127.0.0.1:4222"]) == {}


def test_frame_header_matches_go_layout():
    e2e.set_ring(Ring(encrypt=KEY))
    frame = e2e.seal(SUBJECT, PLAIN, nonce=NONCE)
    assert frame.hex() == (
        "e20102d449a3222222222222222222222222679e692e115222e206423c827e2d9559c83f9eda"
    )
