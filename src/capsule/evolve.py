"""Bước 9 (học dần khi dùng). Bản đầu: chỉ ghi bản ghi sửa vào private/corrections.jsonl.

`capsule update` (chạy lại Bước 5 cho lĩnh vực bị ảnh hưởng bằng thao tác thêm/gộp/thu hẹp từng luật, nạp export mới)
thuộc giai đoạn 3 của lộ trình.
"""
from __future__ import annotations

import datetime as dt
import json

from .common import capsule_dir, read_jsonl


def correct(cfg, right: str, domain: str, situation: str = "", wrong: str = "") -> int:
    p = capsule_dir(cfg) / "private" / "corrections.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"domain": domain, "situation": situation, "wrong": wrong, "right": right, "quote": right,
           "at": dt.datetime.now().isoformat(timespec="seconds"), "applied": False}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return sum(1 for r in read_jsonl(p) if not r.get("applied"))
