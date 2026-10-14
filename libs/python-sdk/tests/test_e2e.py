"""Frame tests shared with the Go CLI codec."""

import base64

import pytest

from puda import e2e

KEY = bytes([0x11]) * 32
NONCE = bytes([0x22]) * 12
SUBJECT = "puda.test.cmd.ping"
PLAIN = b"ping"


@pytest.fixture
def context(tmp_path):
    def create(key=KEY, previous=None):
        path = tmp_path / "e2e.key"
        contents = "encrypt=" + base64.b64encode(key).decode() + "\n"
        if previous:
            contents += "previous=" + base64.b64encode(previous).decode() + "\n"
        path.write_text(contents)
        return e2e.Context(path)
    return create


def test_passthrough_without_key():
    codec = e2e.Context()
    assert codec.seal(SUBJECT, PLAIN) == PLAIN
    assert codec.open_payload(SUBJECT, PLAIN) == PLAIN


def test_round_trip_and_rejects(context):
    codec = context()
    frame = codec.seal(SUBJECT, PLAIN, nonce=NONCE)
    assert frame[:2] == bytes([0xE2, 0x01])
    assert codec.open_payload(SUBJECT, frame) == PLAIN
    with pytest.raises(e2e.E2EError, match="plaintext"):
        codec.open_payload(SUBJECT, PLAIN)
    flipped = bytearray(frame)
    flipped[-1] ^= 0x01
    with pytest.raises(e2e.E2EError, match="failed to open"):
        codec.open_payload(SUBJECT, bytes(flipped))
    with pytest.raises(e2e.E2EError, match="failed to open"):
        codec.open_payload("puda.other.cmd.ping", frame)


def test_previous_key_opens_until_cleared(context):
    old = bytes([0x33]) * 32
    frame = context(old).seal(SUBJECT, PLAIN, nonce=NONCE)
    codec = context(KEY, previous=old)
    assert codec.open_payload(SUBJECT, frame) == PLAIN
    codec.drop_previous()
    with pytest.raises(e2e.E2EError, match="unknown key id"):
        codec.open_payload(SUBJECT, frame)


def test_frame_without_key_reports_encryption(context):
    frame = context().seal(SUBJECT, PLAIN, nonce=NONCE)
    with pytest.raises(e2e.E2EError, match="encryption enabled"):
        e2e.Context().open_payload(SUBJECT, frame)


def test_tls_url_requires_ca():
    with pytest.raises(e2e.E2EError, match="ca_file is required"):
        e2e.connect_kwargs(["tls://127.0.0.1:4222"])
    assert e2e.connect_kwargs(["nats://127.0.0.1:4222"]) == {}


def test_frame_header_matches_go_layout(context):
    frame = context().seal(SUBJECT, PLAIN, nonce=NONCE)
    assert frame.hex() == (
        "e20102d449a3222222222222222222222222679e692e115222e206423c827e2d9559c83f9eda"
    )
