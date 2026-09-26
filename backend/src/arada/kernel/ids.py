"""UUIDv7 identifiers (RFC 9562), generated in the application (ADR-022).

Time-ordered for index locality, non-enumerable, and monotonic within this
process: identifiers generated in the same millisecond still sort in
generation order, which keyset pagination relies on.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = -1
_counter = 0

_MAX_COUNTER = 0xFFF  # 12 bits of rand_a used as a per-millisecond counter


def uuid7() -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms > _last_ms:
            _last_ms = now_ms
            # Start each millisecond at a random point in the lower half so the
            # counter has room to grow while staying unpredictable.
            _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF
        else:
            _counter += 1
            if _counter > _MAX_COUNTER:
                # Counter exhausted within one millisecond: borrow the next
                # millisecond rather than lose ordering.
                _last_ms += 1
                _counter = 0
        ms = _last_ms
        counter = _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (
        (ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | (counter & _MAX_COUNTER) << 64
        | 0b10 << 62
        | rand_b
    )
    return uuid.UUID(int=value)
