"""Parser export ChatGPT (conversations.json): mỗi hội thoại là cây `mapping` + `current_node`.

Cấu trúc dựa trên hiểu biết hiện có. Chạy `pc inspect <path>` trên export thật để xác nhận trước.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from ..schema import Session
from .scrub import scrub
from .timeutil import epoch_to_iso, to_epoch
from .tree import Node, build_turns

# content_type không phải lời nói hiển thị cho người dùng
HIDDEN_CONTENT = {
    "user_editable_context", "model_editable_context", "thoughts", "reasoning_recap",
    "tether_browsing_display", "tether_quote", "execution_output", "system_error",
    "computer_output", "super_widget", "app_pairing_content",
}


def is_chatgpt(conv: dict) -> bool:
    return isinstance(conv, dict) and "mapping" in conv


def message_text(msg: dict) -> str:
    content = msg.get("content") or {}
    ctype = content.get("content_type", "text")
    if ctype in HIDDEN_CONTENT:
        return ""
    if ctype == "code":
        txt = content.get("text") or ""
        return f"```\n{txt}\n```" if txt.strip() else ""
    parts = content.get("parts")
    if parts is None:
        return (content.get("text") or "").strip()
    out: list[str] = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            pt = p.get("content_type", "")
            if pt == "audio_transcription" and p.get("text"):
                out.append(p["text"])
            elif "image" in pt:
                out.append("[image]")
            elif p.get("text"):
                out.append(str(p["text"]))
    return "\n".join(s for s in out if s).strip()


def _visible(msg: Optional[dict]) -> bool:
    if not msg:
        return False
    role = (msg.get("author") or {}).get("role")
    if role not in ("user", "assistant"):
        return False
    meta = msg.get("metadata") or {}
    if meta.get("is_visually_hidden_from_conversation") or meta.get("is_user_system_message"):
        return False
    if role == "assistant" and msg.get("recipient", "all") != "all":
        return False  # gọi tool
    return True


def parse_conversation(conv: dict, counter: Counter | None = None) -> Session:
    mapping: dict[str, Any] = conv.get("mapping") or {}
    sid = str(conv.get("conversation_id") or conv.get("id") or "")

    # Nút hiển thị và cha hiển thị gần nhất
    visible: dict[str, tuple[str, str, Optional[float]]] = {}
    for nid, node in mapping.items():
        msg = node.get("message")
        if not _visible(msg):
            continue
        text = message_text(msg)
        if not text:
            continue
        visible[nid] = (msg["author"]["role"], scrub(text, counter), to_epoch(msg.get("create_time")))

    def vis_parent(nid: str) -> Optional[str]:
        seen = set()
        p = (mapping.get(nid) or {}).get("parent")
        while p is not None and p not in visible and p not in seen:
            seen.add(p)
            p = (mapping.get(p) or {}).get("parent")
        return p if p in visible else None

    nodes = {
        nid: Node(id=nid, role=role, text=text, created_at=ts, parent=vis_parent(nid), order=i)
        for i, (nid, (role, text, ts)) in enumerate(visible.items())
    }

    leaf = conv.get("current_node")
    # current_node có thể là nút ẩn: đi lên tới nút hiển thị
    while leaf is not None and leaf not in visible:
        leaf = (mapping.get(leaf) or {}).get("parent")

    turns = build_turns(nodes, leaf, epoch_to_iso)
    return Session(
        session_id=f"chatgpt:{sid}",
        source="chatgpt",
        title=scrub(conv.get("title") or "", counter),
        created_at=epoch_to_iso(to_epoch(conv.get("create_time"))),
        n_turns=sum(1 for t in turns if t.on_active_path),
        turns=turns,
    )
