"""Optional AES-256-GCM framing for PUDA NATS payloads.

Encryption is off when no lab key is configured. The frame is shared with the
Go CLI in ``apps/cli/internal/nats/e2e.go``.
"""

from __future__ import annotations

import base64
import hashlib
import os
import ssl
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = 0xE2
VERSION = 0x01
_HEADER_LEN = 18
_TAG_LEN = 16
_KEY_LEN = 32

KEYRING_BUCKET = "E2E_KEYRING"
KEYRING_KEY = "current"
KEYFILES_BUCKET = "E2E_KEYFILES"


class E2EError(Exception):
    """A payload could not be sealed or opened."""


@dataclass
class Ring:
    """The key that seals new messages, plus at most one other key."""

    encrypt: bytes
    previous: bytes | None = None
    persistent: bool = False
    path: Path | None = None

    def encrypt_kid(self) -> bytes:
        return kid_for(self.encrypt)

    def decrypt_kids(self) -> list[bytes]:
        kids = [self.encrypt_kid()]
        if self.previous is not None:
            kids.append(kid_for(self.previous))
        return kids

    def key_for(self, key_id: bytes) -> bytes:
        if key_id == self.encrypt_kid():
            return self.encrypt
        if self.previous is not None and key_id == kid_for(self.previous):
            return self.previous
        raise E2EError("unknown key id")


_lock = threading.Lock()
_ring: Ring | None = None
_loaded = False


def kid_for(key: bytes) -> bytes:
    return hashlib.sha256(key).digest()[:4]


def kid_hex(key_id: bytes) -> str:
    return key_id.hex()


def kv_aad(bucket: str, key: str) -> str:
    return f"kv:{bucket}:{key}"


def enabled() -> bool:
    return current() is not None


def current() -> Ring | None:
    global _loaded, _ring
    with _lock:
        if not _loaded:
            _ring = _load_from_env()
            _loaded = True
        return _ring


def reload() -> Ring | None:
    global _loaded, _ring
    with _lock:
        _ring = _load_from_env()
        _loaded = True
        return _ring


def set_ring(ring: Ring | None) -> None:
    """Install a ring for this process. Tests use this to avoid the environment."""
    global _loaded, _ring
    with _lock:
        _ring = ring
        _loaded = True


def reset() -> None:
    global _loaded, _ring
    with _lock:
        _ring = None
        _loaded = False


def seal(subject: str, plaintext: bytes, *, nonce: bytes | None = None) -> bytes:
    ring = current()
    if ring is None:
        return plaintext
    if nonce is None:
        nonce = os.urandom(12)
    if len(nonce) != 12:
        raise E2EError("nonce must be 12 bytes")
    key_id = ring.encrypt_kid()
    ciphertext = AESGCM(ring.encrypt).encrypt(nonce, plaintext, subject.encode())
    return bytes([MAGIC, VERSION]) + key_id + nonce + ciphertext


def open_payload(subject: str, data: bytes) -> bytes:
    framed = _is_frame(data)
    ring = current()
    if ring is None:
        if framed:
            raise E2EError("peer has encryption enabled")
        return data
    if not framed:
        raise E2EError("plaintext payload rejected while encryption is enabled")
    key_id = data[2:6]
    nonce = data[6:18]
    key = ring.key_for(key_id)
    try:
        return AESGCM(key).decrypt(nonce, data[_HEADER_LEN:], subject.encode())
    except Exception as exc:
        raise E2EError("failed to open payload") from exc


def connect_kwargs(servers: list[str]) -> dict:
    """TLS settings for nats-py. A tls:// URL without PUDA_NATS_CA is an error."""
    schemes = set()
    for server in servers:
        if server.startswith("tls://"):
            schemes.add("tls")
        elif server.startswith("nats://"):
            schemes.add("nats")
        else:
            raise E2EError(f"unsupported NATS URL {server}")
    if not schemes or schemes == {"nats"}:
        return {}
    if schemes != {"tls"}:
        raise E2EError("NATS server URLs must all use tls:// or all use nats://")
    ca = os.environ.get("PUDA_NATS_CA", "").strip()
    if not ca:
        raise E2EError("PUDA_NATS_CA is not set; a tls:// NATS URL needs the path to the server CA file (ca.pem)")
    return {"tls": ssl.create_default_context(cafile=ca)}


def adopt_record(payload: bytes) -> bool:
    """Apply a keyring record. Returns True when the local ring changed."""
    import json

    record = json.loads(payload)
    new_key = _decode_key(record["new_key"])
    old_key = _decode_key(record["old_key"])
    encrypt_kid = bytes.fromhex(record["encrypt_kid"])
    if encrypt_kid == kid_for(new_key):
        encrypt, extra = new_key, old_key
    elif encrypt_kid == kid_for(old_key):
        encrypt, extra = old_key, new_key
    else:
        raise E2EError("keyring encrypt id does not match either key")
    ring = current()
    path = ring.path if ring is not None else _key_path()
    persistent = path is not None
    updated = Ring(encrypt=encrypt, previous=extra, persistent=persistent, path=path)
    if ring is not None and ring.encrypt == updated.encrypt and ring.previous == updated.previous:
        return False
    if path is not None:
        _write_key_file(path, updated)
    set_ring(updated)
    return True


def drop_previous() -> None:
    ring = current()
    if ring is None or ring.previous is None:
        return
    updated = Ring(encrypt=ring.encrypt, previous=None, persistent=ring.persistent, path=ring.path)
    if ring.path is not None:
        _write_key_file(ring.path, updated)
    set_ring(updated)


def _is_frame(data: bytes) -> bool:
    return len(data) >= _HEADER_LEN + _TAG_LEN and data[0] == MAGIC and data[1] == VERSION


def _load_from_env() -> Ring | None:
    path = _key_path()
    if path is None or not path.is_file():
        return None
    encrypt, previous = _read_key_file(path)
    if encrypt is None:
        return None
    return Ring(encrypt=encrypt, previous=previous, persistent=True, path=path)


def _key_path() -> Path | None:
    raw = os.environ.get("PUDA_E2E_KEY_FILE", "").strip()
    if not raw:
        return None
    return Path(raw)


def _decode_key(value: str) -> bytes:
    text = value.strip()
    try:
        key = base64.b64decode(text, validate=True)
    except Exception:
        key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if len(key) != _KEY_LEN:
        raise E2EError("lab key must be 32 bytes")
    return key


def _read_key_file(path: Path) -> tuple[bytes | None, bytes | None]:
    encrypt: bytes | None = None
    previous: bytes | None = None
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        field, value = stripped.split("=", 1)
        if field == "encrypt":
            encrypt = _decode_key(value)
        elif field == "previous" and value.strip():
            previous = _decode_key(value)
    return encrypt, previous


def _write_key_file(path: Path, ring: Ring) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"encrypt={base64.b64encode(ring.encrypt).decode()}"]
    if ring.previous is not None:
        lines.append(f"previous={base64.b64encode(ring.previous).decode()}")
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    id_path = path.with_name(path.name + ".id")
    if not id_path.exists():
        import uuid

        id_path.write_text(uuid.uuid4().hex + "\n")
        os.chmod(id_path, 0o600)


def key_file_id(path: Path | None = None) -> str | None:
    ring = current()
    target = path or (ring.path if ring else None)
    if target is None:
        return None
    id_path = target.with_name(target.name + ".id")
    if not id_path.is_file():
        return None
    return id_path.read_text().strip()
