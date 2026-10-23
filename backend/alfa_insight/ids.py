"""Идентификаторы `{prefix}_{ULID}`: 26 символов Crockford base32, сортируются по времени."""

from __future__ import annotations

import secrets
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = threading.Lock()
_last_ms = -1
_last_rand = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def ulid() -> str:
    """Монотонный ULID: внутри одной миллисекунды случайная часть увеличивается на 1."""
    global _last_ms, _last_rand
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            rand = (_last_rand + 1) & ((1 << 80) - 1)
        else:
            rand = secrets.randbits(80)
        _last_ms, _last_rand = ms, rand
    return _encode(ms, 10) + _encode(rand, 16)


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"
