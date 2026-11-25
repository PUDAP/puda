"""Generate the PUDA Edge Protocol 1.0 E2E test vectors.

Run from the repository root with the Python SDK importable:

    uv run python docs/edge-protocol/v1.0/vectors/generate_vectors.py

Keys and nonces are fixed, so the output is byte-for-byte reproducible. The
keys are test values only and are never used by a real deployment.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from puda import e2e

OUT = Path(__file__).with_name("e2e-vectors.json")

K1 = bytes(range(0x00, 0x20))  # "old" / current lab key
K2 = bytes(range(0x20, 0x40))  # "new" key introduced by a rotation
MID = "esp32-demo"


def nonce(seed: int) -> bytes:
    return bytes((seed + i) & 0xFF for i in range(12))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def seal(key: bytes, aad: str, plaintext: bytes, n: bytes) -> bytes:
    frame = e2e._seal(e2e.Ring(encrypt=key), aad, plaintext, nonce=n)
    # Independent check of the frame layout with the raw AEAD primitive.
    assert frame[0] == 0xE2 and frame[1] == 0x01
    assert frame[2:6] == e2e.kid_for(key)
    assert frame[6:18] == n
    assert AESGCM(key).decrypt(n, frame[18:], aad.encode()) == plaintext
    return frame


def compact(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


command = {
    "header": {"version": "1.0", "message_type": "command", "user_id": "00000000-0000-4000-8000-000000000000",
               "username": "vector", "machine_id": MID, "run_id": "11111111-2222-4333-8444-555555555555",
               "timestamp": "2026-01-01T00:00:00Z"},
    "command": {"name": "move_to", "params": {"x_mm": 1.5, "y_mm": 0, "z_mm": 10}, "step_number": 1,
                "version": "1.0", "machine_id": MID},
}
state = {"timestamp": "2026-01-01T00:00:01Z", "state": "busy", "run_id": "11111111-2222-4333-8444-555555555555"}
pong = {"status": "pong", "machine_id": MID, "timestamp": "2026-01-01T00:00:02Z", "sdk_version": "0.1.0",
        "uptime_seconds": 12.5, "run_status": "idle", "tlm_streams": [],
        "e2e_encrypt_kid": e2e.kid_hex(e2e.kid_for(K1)), "e2e_decrypt_kids": [e2e.kid_hex(e2e.kid_for(K1))],
        "e2e_persist": True}
phase1 = {"new_key": b64(K2), "old_key": b64(K1), "encrypt_kid": e2e.kid_hex(e2e.kid_for(K1))}
phase2 = {**phase1, "encrypt_kid": e2e.kid_hex(e2e.kid_for(K2))}

positive = []


def add(name, key, aad, plaintext, n, note):
    frame = seal(key, aad, plaintext, n)
    positive.append({
        "name": name, "note": note, "key_b64": b64(key), "kid_hex": e2e.kid_for(key).hex(),
        "aad": aad, "nonce_hex": n.hex(), "plaintext_utf8": plaintext.decode(), "frame_hex": frame.hex(),
    })


add("queue_command", K1, f"puda.{MID}.cmd.queue", compact(command), nonce(0x00),
    "Command published on the queue subject; AAD is the publish subject (also the subject of the JetStream delivery).")
add("state_kv_put", K1, f"kv:MACHINE_STATE:{MID}", compact(state), nonce(0x10),
    "MACHINE_STATE value; AAD is kv:<bucket>:<key>, not the $KV subject.")
add("ping_request", K1, f"puda.{MID}.cmd.ping", b"ping", nonce(0x20),
    "Direct ping body. The broadcast ping uses AAD puda.cmd.ping.")
add("pong_reply", K1, "_INBOX.vector.reply", compact(pong), nonce(0x30),
    "Pong reply; AAD is the request's reply subject (the inbox), not the ping subject.")
add("keyring_phase1", K1, "kv:E2E_KEYRING:current", compact(phase1), nonce(0x40),
    "Rotation phase 1 (new key decrypt-only). Always sealed with the OLD key.")
add("keyring_phase2", K1, "kv:E2E_KEYRING:current", compact(phase2), nonce(0x50),
    "Rotation phase 2 (switch to new key). Still sealed with the OLD key.")
add("queue_command_new_key", K2, f"puda.{MID}.cmd.queue", compact(command), nonce(0x60),
    "Same command after the switch, sealed with the NEW key.")

base = bytes.fromhex(positive[0]["frame_hex"])
tampered = bytearray(base)
tampered[-1] ^= 0x01
unknown_kid = bytearray(base)
unknown_kid[2:6] = b"\x00\x00\x00\x00"

negative = [
    {"name": "wrong_aad", "frame_hex": base.hex(), "aad": f"puda.{MID}.cmd.immediate", "keys_b64": [b64(K1)],
     "expect": "reject", "why": "AAD binds the frame to its subject; replay on another subject must fail."},
    {"name": "tampered_tag", "frame_hex": bytes(tampered).hex(), "aad": f"puda.{MID}.cmd.queue", "keys_b64": [b64(K1)],
     "expect": "reject", "why": "GCM authentication failure."},
    {"name": "unknown_kid", "frame_hex": bytes(unknown_kid).hex(), "aad": f"puda.{MID}.cmd.queue", "keys_b64": [b64(K1)],
     "expect": "reject", "why": "Key id matches neither the encrypt nor the previous key."},
    {"name": "plaintext_while_enabled", "frame_hex": compact(command).hex(), "aad": f"puda.{MID}.cmd.queue",
     "keys_b64": [b64(K1)], "expect": "reject", "why": "An edge with a key configured rejects unframed payloads."},
    {"name": "frame_while_disabled", "frame_hex": base.hex(), "aad": f"puda.{MID}.cmd.queue", "keys_b64": [],
     "expect": "reject", "why": "An edge without a key rejects framed payloads (peer has encryption enabled)."},
    {"name": "short_frame_is_not_a_frame", "frame_hex": base[:33].hex(), "aad": f"puda.{MID}.cmd.queue",
     "keys_b64": [], "expect": "accept_as_plaintext",
     "why": "Fewer than 34 bytes (18 header + 16 tag) is not a frame; with encryption off it is passed through as plaintext."},
]

# Cross-check the negative cases against the reference implementation.
for case in negative:
    data = bytes.fromhex(case["frame_hex"])
    keys = [base64.b64decode(k) for k in case["keys_b64"]]
    ring = e2e.Ring(encrypt=keys[0]) if keys else None
    try:
        e2e._open_payload(ring, case["aad"], data)
        outcome = "accept_as_plaintext" if ring is None else "accept"
    except e2e.E2EError:
        outcome = "reject"
    assert outcome == case["expect"], (case["name"], outcome)

doc = {
    "protocol": "PUDA Edge Protocol 1.0",
    "frame": {"magic": "0xE2", "version": "0x01", "layout": "magic(1) version(1) kid(4) nonce(12) ciphertext||tag(16)",
              "kid": "first 4 bytes of SHA-256(key)", "aead": "AES-256-GCM, 128-bit tag"},
    "positive": positive,
    "negative": negative,
}
OUT.write_text(json.dumps(doc, indent=2) + "\n")
print(f"wrote {OUT} ({len(positive)} positive, {len(negative)} negative)")
