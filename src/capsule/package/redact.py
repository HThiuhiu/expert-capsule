"""Rà soát phần chia sẻ được của capsule: che PII bằng regex, gắn cờ đoạn trích bằng chứng bị lọt ra ngoài private/.

Rà soát đầy đủ trước khi chia sẻ (tên dự án nội bộ, tên người khác, viết lại tình huống) thuộc `capsule share`
(giai đoạn 3). Ở đây chỉ chặn hai lỗi rẻ nhất.
"""
from __future__ import annotations

from collections import Counter

from pc.ingest.scrub import scrub
from pc.textutil import norm_ws

MIN_LEAK = 40  # đoạn trích dài từ 40 ký tự xuất hiện nguyên văn ngoài private/ thì gắn cờ


def clean(text: str, counter: Counter) -> str:
    return scrub(text, counter)


def leaks(files: dict[str, str], quotes: list[str], allowed: list[str]) -> list[dict]:
    ok = [norm_ws(a) for a in allowed]
    out = []
    for name, text in files.items():
        t = norm_ws(text)
        for q in quotes:
            q = norm_ws(q)
            if len(q) >= MIN_LEAK and q in t and not any(q in a for a in ok):
                out.append({"file": name, "quote": q[:120]})
    return out
