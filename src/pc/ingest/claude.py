"""Parser export Claude (conversations.json): `chat_messages` phẳng, `sender` = human|assistant.

Nếu tin nhắn có `parent_message_uuid` thì dựng cây (giữ nhánh sửa/regenerate). Không có thì coi là chuỗi phẳng.
Cấu trúc dựa trên hiểu biết hiện có. Chạy `pc inspect <path>` trên export thật để xác nhận trước.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from ..schema import Session
from .scrub import scrub
from .timeutil import epoch_to_iso, to_epoch
from .tree import Node, build_turns

ROOT_SENTINEL = "00000000-0000-4000-8000-000000000000"
_ROLE = {"human": "user", "user": "user", "assistant": "assistant"}


def is_claude(conv: dict) -> bool:
    return isinstance(conv, dict) and "chat_messages" in conv


def message_text(msg: dict, include_attachments: bool = True) -> str:
    parts: list[str] = []
    content = msg.get("content")
    if isinstance(content, list) and content:
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
    if not parts and msg.get("text"):
        parts.append(msg["text"])
    if include_attachments:
        for a in msg.get("attachments") or []:
            body = (a.get("extracted_content") or "").strip()
            name = a.get("file_name") or "file"
            if body:
                parts.append(f"[attachment: {name}]\n{body}")
        for f in msg.get("files") or []:
            name = f.get("file_name") if isinstance(f, dict) else None
            parts.append(f"[file: {name or 'file'}]")
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def parse_conversation(conv: dict, counter: Counter | None = None, include_attachments: bool = True) -> Session:
    sid = str(conv.get("uuid") or conv.get("id") or "")
    msgs = conv.get("chat_messages") or []
    has_tree = any("parent_message_uuid" in m for m in msgs)

    nodes: dict[str, Node] = {}
    prev: Optional[str] = None
    for i, m in enumerate(msgs):
        role = _ROLE.get(m.get("sender"))
        if role is None:
            continue
        mid = str(m.get("uuid") or f"{sid}:{i}")
        text = message_text(m, include_attachments)
        if has_tree:
            parent = m.get("parent_message_uuid")
            parent = None if parent in (None, "", ROOT_SENTINEL) else str(parent)
        else:
            parent = prev
        if not text:
            # nút rỗng: con của nó sẽ trỏ về cha của nó (xử lý bằng bảng chuyển hướng bên dưới)
            nodes[mid] = Node(id=mid, role="__empty__", text="", created_at=None, parent=parent, order=i)
        else:
            nodes[mid] = Node(id=mid, role=role, text=scrub(text, counter),
                              created_at=to_epoch(m.get("created_at")), parent=parent, order=i)
        prev = mid

    # Bỏ nút rỗng, nối con lên ông
    empty = {k for k, n in nodes.items() if n.role == "__empty__"}

    def up(p: Optional[str]) -> Optional[str]:
        seen = set()
        while p in empty and p not in seen:
            seen.add(p)
            p = nodes[p].parent
        return p

    for n in nodes.values():
        n.parent = up(n.parent)
    for k in empty:
        nodes.pop(k)

    leaf = conv.get("current_leaf_message_uuid")
    leaf = up(str(leaf)) if leaf else None
    if leaf is None and not has_tree and nodes:
        leaf = list(nodes)[-1]

    turns = build_turns(nodes, leaf, epoch_to_iso)
    return Session(
        session_id=f"claude:{sid}",
        source="claude",
        title=scrub(conv.get("name") or "", counter),
        created_at=epoch_to_iso(to_epoch(conv.get("created_at"))),
        n_turns=sum(1 for t in turns if t.on_active_path),
        turns=turns,
    )
