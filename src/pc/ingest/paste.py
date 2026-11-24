"""Parser văn bản dán (Gemini hoặc nguồn không có export): file .txt/.md, mỗi lượt mở đầu bằng nhãn vai ở đầu dòng.

Nhãn user: "User:", "You:", "Bạn:", "Tôi:", "Me:". Nhãn assistant: "Gemini:", "Model:", "AI:", "Assistant:",
"ChatGPT:", "Claude:". Nhiều hội thoại trong một file: ngăn bằng dòng "=== <tiêu đề> ===" (hoặc "---" đứng riêng).
Không có thời gian thật: created_at lấy từ thời gian sửa file. Không có nhánh.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from ..schema import Session, Turn
from ..textutil import approx_tokens, detect_lang, has_code
from .scrub import scrub
from .timeutil import epoch_to_iso

_USER = r"(?:user|you|bạn|tôi|me|human)"
_ASST = r"(?:gemini|model|ai|assistant|chatgpt|claude|bot)"
_ROLE = re.compile(rf"^\s*(\*\*)?({_USER}|{_ASST})(\*\*)?\s*:\s?(.*)$", re.I)
_SEP = re.compile(r"^\s*(?:===+\s*(.*?)\s*===+|---+)\s*$")
_IS_USER = re.compile(rf"^{_USER}$", re.I)


def looks_like_paste(text: str) -> bool:
    roles = [m.group(2) for m in map(_ROLE.match, text.splitlines()) if m]
    return any(_IS_USER.match(r) for r in roles) and any(not _IS_USER.match(r) for r in roles)


def _split(text: str) -> list[tuple[str, list[str]]]:
    convs, title, lines = [], "", []
    for line in text.splitlines():
        m = _SEP.match(line)
        if m:
            if any(l.strip() for l in lines):
                convs.append((title, lines))
            title, lines = (m.group(1) or "").strip(), []
            continue
        lines.append(line)
    if any(l.strip() for l in lines):
        convs.append((title, lines))
    return convs


def parse_text(text: str, name: str, created_at: str | None, counter: Counter | None = None) -> list[Session]:
    out = []
    for k, (title, lines) in enumerate(_split(text)):
        turns: list[tuple[str, list[str]]] = []
        for line in lines:
            m = _ROLE.match(line)
            if m:
                turns.append(("user" if _IS_USER.match(m.group(2)) else "assistant", [m.group(4)]))
            elif turns:
                turns[-1][1].append(line)
        sid = "paste:" + hashlib.sha1(f"{name}|{k}|{title}".encode()).hexdigest()[:16]
        ts: list[Turn] = []
        prev = None
        for i, (role, body) in enumerate(turns):
            t = scrub("\n".join(body).strip(), counter)
            if not t:
                continue
            tid = f"{sid}:{i}"
            ts.append(Turn(turn_id=tid, idx=len(ts), role=role, text=t, created_at=created_at, on_active_path=True,
                           sibling_count=1, sibling_rank=0, lang=detect_lang(t), n_tokens=approx_tokens(t),
                           has_code=has_code(t), parent_id=prev))
            prev = tid
        first_user = next((t.text for t in ts if t.role == "user"), "")
        out.append(Session(session_id=sid, source="gemini", title=title or first_user[:60], created_at=created_at,
                           n_turns=len(ts), turns=ts))
    return out


def parse_file(path: Path, counter: Counter | None = None) -> list[Session]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not looks_like_paste(text):
        return []
    return parse_text(text, path.name, epoch_to_iso(path.stat().st_mtime), counter)
