"""Ingest (B1): đọc export ChatGPT/Claude (file .json, .zip hoặc thư mục) -> Session."""
from __future__ import annotations

import json
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ..schema import Session
from . import chatgpt, claude, paste


@dataclass
class IngestResult:
    sessions: list[Session] = field(default_factory=list)       # đã giữ
    dropped_short: list[Session] = field(default_factory=list)  # < min_user_turns
    n_raw: Counter = field(default_factory=Counter)             # theo nguồn
    n_unknown: int = 0
    n_dup: int = 0
    errors: list[str] = field(default_factory=list)
    scrub_counts: Counter = field(default_factory=Counter)
    files: list[str] = field(default_factory=list)


def _iter_json_blobs(path: Path) -> Iterator[tuple[str, object]]:
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and (p.suffix.lower() == ".zip" or _is_conv_name(p.name)):
                yield from _iter_json_blobs(p)
        return
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for name in sorted(z.namelist()):
                if _is_conv_name(Path(name).name):
                    with z.open(name) as f:
                        yield f"{path.name}!{name}", json.load(f)
        return
    with open(path, encoding="utf-8") as f:
        yield str(path), json.load(f)


def _paste_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in (".txt", ".md"))
    return [path] if path.suffix.lower() in (".txt", ".md") else []


def _is_conv_name(name: str) -> bool:
    n = name.lower()
    return n.endswith(".json") and n.startswith("conversations")


def iter_conversations(path: Path) -> Iterator[tuple[str, dict]]:
    """Trả (tên file, hội thoại thô)."""
    for fname, blob in _iter_json_blobs(path):
        items = blob if isinstance(blob, list) else (blob.get("conversations") if isinstance(blob, dict) else None)
        if items is None and isinstance(blob, dict):
            items = [blob]
        for conv in items or []:
            yield fname, conv


def ingest(path: Path, min_user_turns: int = 2, include_attachments: bool = True) -> IngestResult:
    res = IngestResult()
    seen: set[str] = set()
    files: set[str] = set()
    for fname, conv in iter_conversations(path):
        files.add(fname)
        try:
            if chatgpt.is_chatgpt(conv):
                res.n_raw["chatgpt"] += 1
                s = chatgpt.parse_conversation(conv, res.scrub_counts)
            elif claude.is_claude(conv):
                res.n_raw["claude"] += 1
                s = claude.parse_conversation(conv, res.scrub_counts, include_attachments)
            else:
                res.n_unknown += 1
                continue
        except Exception as e:  # một hội thoại hỏng không làm hỏng cả lần chạy
            res.errors.append(f"{fname}: {type(e).__name__}: {e}")
            continue
        if s.session_id in seen:
            res.n_dup += 1
            continue
        seen.add(s.session_id)
        (res.sessions if s.n_user_turns >= min_user_turns else res.dropped_short).append(s)
    # văn bản dán (Gemini...): .txt/.md có nhãn vai đầu dòng
    for p in _paste_files(path):
        try:
            got = paste.parse_file(p, res.scrub_counts)
        except Exception as e:
            res.errors.append(f"{p.name}: {type(e).__name__}: {e}")
            continue
        if got:
            files.add(p.name)
        for s in got:
            res.n_raw["gemini"] += 1
            if s.session_id in seen:
                res.n_dup += 1
                continue
            seen.add(s.session_id)
            (res.sessions if s.n_user_turns >= min_user_turns else res.dropped_short).append(s)
    res.files = sorted(files)
    res.sessions.sort(key=lambda s: (s.created_at or "", s.session_id))
    return res


def write_sessions(sessions: list[Session], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for s in sessions:
            f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")


def read_sessions(path: Path) -> list[Session]:
    with open(path, encoding="utf-8") as f:
        return [Session.from_dict(json.loads(line)) for line in f if line.strip()]
