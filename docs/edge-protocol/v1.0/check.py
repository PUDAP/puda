"""Self-check for the PUDA Edge Protocol 1.0 artifacts.

1. Validates every example payload against its JSON Schema.
2. Re-opens every E2E vector with the raw AES-256-GCM primitive and with the
   reference implementation (puda.e2e), and checks the negative cases.

    uv run --with jsonschema python docs/edge-protocol/v1.0/check.py

Exit status is non-zero on any failure.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import jsonschema
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = Path(__file__).parent
EXAMPLES = {
    "nats-message": ["command-*.json", "response-*.json", "update-*.json"],
    "pong": ["pong*.json"],
    "machine-state": ["machine-state.json"],
    "machine-commands": ["machine-commands.json"],
    "telemetry": ["tlm-*.json"],
    "events": ["evt-*.json"],
}
failures: list[str] = []


def schema(name: str) -> dict:
    return json.loads((HERE / "schemas" / f"{name}.schema.json").read_text())


def check_examples() -> int:
    count = 0
    for name, patterns in EXAMPLES.items():
        s = schema(name)
        jsonschema.Draft202012Validator.check_schema(s)
        validator = jsonschema.Draft202012Validator(s)
        for pattern in patterns:
            for path in sorted((HERE / "examples").glob(pattern)):
                for error in validator.iter_errors(json.loads(path.read_text())):
                    failures.append(f"{path.name}: {error.message} at {list(error.absolute_path)}")
                count += 1
    keyring = jsonschema.Draft202012Validator(schema("keyring-record"))
    for record in json.loads((HERE / "examples" / "keyring-records.json").read_text()):
        record = {k: v for k, v in record.items() if not k.startswith("_")}
        for error in keyring.iter_errors(record):
            failures.append(f"keyring-records.json: {error.message}")
        count += 1
    return count


def raw_open(keys: list[bytes], aad: str, data: bytes) -> bytes:
    """Independent implementation of spec §11.3 (receive rules)."""
    framed = len(data) >= 34 and data[0] == 0xE2 and data[1] == 0x01
    if not keys:
        if framed:
            raise ValueError("peer has encryption enabled")
        return data
    if not framed:
        raise ValueError("plaintext rejected")
    by_kid = {hashlib.sha256(k).digest()[:4]: k for k in keys}
    key = by_kid.get(data[2:6])
    if key is None:
        raise ValueError("unknown kid")
    return AESGCM(key).decrypt(data[6:18], data[18:], aad.encode())


def check_vectors() -> int:
    doc = json.loads((HERE / "vectors" / "e2e-vectors.json").read_text())
    try:
        from puda import e2e  # reference implementation, optional
    except ImportError:
        e2e = None
    for v in doc["positive"]:
        key = base64.b64decode(v["key_b64"])
        frame = bytes.fromhex(v["frame_hex"])
        if hashlib.sha256(key).digest()[:4].hex() != v["kid_hex"]:
            failures.append(f"{v['name']}: kid mismatch")
        if frame[6:18].hex() != v["nonce_hex"]:
            failures.append(f"{v['name']}: nonce not at bytes 6..17")
        if raw_open([key], v["aad"], frame).decode() != v["plaintext_utf8"]:
            failures.append(f"{v['name']}: raw AES-GCM open mismatch")
        if e2e is not None:
            ring = e2e.Ring(encrypt=key)
            if e2e._open_payload(ring, v["aad"], frame).decode() != v["plaintext_utf8"]:
                failures.append(f"{v['name']}: puda.e2e open mismatch")
            resealed = e2e._seal(ring, v["aad"], v["plaintext_utf8"].encode(), nonce=bytes.fromhex(v["nonce_hex"]))
            if resealed != frame:
                failures.append(f"{v['name']}: puda.e2e seal is not byte-identical")
    for v in doc["negative"]:
        keys = [base64.b64decode(k) for k in v["keys_b64"]]
        try:
            raw_open(keys, v["aad"], bytes.fromhex(v["frame_hex"]))
            outcome = "accept_as_plaintext" if not keys else "accept"
        except Exception:
            outcome = "reject"
        if outcome != v["expect"]:
            failures.append(f"negative {v['name']}: expected {v['expect']}, got {outcome}")
    return len(doc["positive"]) + len(doc["negative"])


if __name__ == "__main__":
    n_examples = check_examples()
    n_vectors = check_vectors()
    for failure in failures:
        print("FAIL", failure)
    print(f"{n_examples} examples, {n_vectors} vectors, {len(failures)} failures")
    sys.exit(1 if failures else 0)
