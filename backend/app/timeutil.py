import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_as_of(value: Optional[str]) -> int:
    """None -> now. Accepts epoch milliseconds or an ISO-8601 string. Future times are clamped to now."""
    now = now_ms()
    if value in (None, "", "now"):
        return now
    try:
        if str(value).lstrip("-").isdigit():
            t = int(value)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            t = int(dt.timestamp() * 1000)
    except ValueError:
        raise HTTPException(422, f"Bad as_of value: {value!r} (use epoch ms or ISO-8601)")
    return min(t, now)
