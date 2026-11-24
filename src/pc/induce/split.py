"""C2: chia phiên theo thời gian 70/10/20. Đóng băng vào splits.json ở lần chạy đầu.

Chia theo phiên nên một chain (nằm trong một phiên) không bao giờ ở hai split.
"""
from __future__ import annotations

import json
from pathlib import Path

RATIOS = (0.7, 0.1, 0.2)


def split_sessions(sessions: list[tuple[str, str | None]], ratios=RATIOS) -> dict[str, str]:
    """sessions: [(session_id, created_at)]. Cũ nhất vào train, mới nhất vào test."""
    order = sorted(sessions, key=lambda s: (s[1] or "", s[0]))
    n = len(order)
    n_train = round(n * ratios[0])
    n_dev = round(n * ratios[1])
    out = {}
    for i, (sid, _) in enumerate(order):
        out[sid] = "train" if i < n_train else "dev" if i < n_train + n_dev else "test"
    return out


def load_or_create(path: Path, sessions: list[tuple[str, str | None]]) -> tuple[dict[str, str], bool]:
    """Trả (split theo phiên, mới tạo?). File đã có thì giữ nguyên: test đã khoá không được đổi."""
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        return d["sessions"], False
    sp = split_sessions(sessions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ratios": RATIOS, "by": "session created_at", "sessions": sp},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return sp, True
