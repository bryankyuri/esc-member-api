"""UUIDv7 primary keys.

Every table uses a UUID rather than an auto-incrementing integer, so ids in
URLs reveal nothing and cannot be walked. v7 rather than v4 because it starts
with a millisecond timestamp: rows stay roughly insert-ordered, so indexes do
not fragment and "ORDER BY id" still means "oldest first".

Python's stdlib has no uuid7() yet (it is RFC 9562, added after uuid4), hence
this small generator.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

__all__ = ["new_id", "uuid7", "is_uuid"]


def uuid7(when: datetime | None = None) -> str:
    """RFC 9562 UUIDv7: 48-bit ms timestamp | version 7 | variant | random."""
    ms = int((when or datetime.now(timezone.utc)).timestamp() * 1000)
    value = (
        (ms & 0xFFFFFFFFFFFF) << 80          # unix_ts_ms
        | 0x7 << 76                          # version
        | secrets.randbits(12) << 64         # rand_a
        | 0b10 << 62                         # variant
        | secrets.randbits(62)               # rand_b
    )
    h = f"{value:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def new_id() -> str:
    """Default for every primary key column."""
    return uuid7()


def is_uuid(value: str) -> bool:
    """Shape check for path parameters — cheap rejection of junk ids."""
    if not isinstance(value, str) or len(value) != 36:
        return False
    parts = value.split("-")
    if [len(p) for p in parts] != [8, 4, 4, 4, 12]:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in value.replace("-", ""))
