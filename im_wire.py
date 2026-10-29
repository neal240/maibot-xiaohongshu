"""Small XHS web IM wire encoder; uses the public protobuf and RSA formats."""
from __future__ import annotations

import time
import uuid

_RSA_MODULUS = int(
    'd321555d67813eace010dc27e72ab14876a9b671c7d58d3c9c2064cd60f7e9f7'
    '9ad3799657b35a1b7654d82725408a71549d5ade11e74bbf1ec39b549ed32116a'
    'ffd4f6b03f2c9c44d91f84157b159a8a225150916e2716cc82dc8fd62385e5a'
    '01c83b784c139462a1dd45d47d96ebb4f5068c42b3de8590123a03565a9e5aed', 16)


def _unsigned(value: int) -> bytes:
    if value < 0: raise ValueError('negative integer')
    parts = []
    while value >= 128:
        value, remainder = divmod(value, 128)
        parts.append(remainder | 128)
    parts.append(value)
    return bytes(parts)


def _integer(number: int, value: int) -> bytes:
    return _unsigned(number * 8) + _unsigned(value)


def _bytes(number: int, value: bytes) -> bytes:
    return _unsigned(number * 8 + 2) + _unsigned(len(value)) + value


def encode_text(sender: str, recipient: str, text: str, *, message_id: str | None = None,
                timestamp_ms: int | None = None) -> bytes:
    mid = message_id or str(uuid.uuid4())
    now = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    values = [mid, '', sender, recipient, text, '', '']
    fields = [_bytes(n, v.encode('utf-8')) for n, v in zip((1, 3, 4, 5, 6, 8, 11), values)]
    inner = b''.join((fields[0], _integer(2, now), *fields[1:5], _integer(7, 1),
                      fields[5], _integer(9, 0), fields[6], _integer(12, 1)))
    return _integer(1, 1) + _bytes(9, inner)


def encrypt_payload(payload: bytes) -> bytes:
    from Crypto.Cipher import PKCS1_v1_5
    from Crypto.PublicKey import RSA
    key = RSA.construct((_RSA_MODULUS, 65537))
    cipher = PKCS1_v1_5.new(key)
    limit = key.size_in_bytes() - 11
    return b''.join(cipher.encrypt(payload[i:i + limit]) for i in range(0, len(payload), limit))
