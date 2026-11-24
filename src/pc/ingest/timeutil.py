from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def to_epoch(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def epoch_to_iso(v: Optional[float]) -> Optional[str]:
    if v is None:
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc).isoformat().replace("+00:00", "Z")
