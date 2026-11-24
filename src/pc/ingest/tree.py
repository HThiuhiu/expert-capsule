"""Dựng cây lượt hiển thị và tuyến tính hoá thành Turn (B1).

Đầu vào là các nút đã lọc (chỉ user/assistant có nội dung), mỗi nút trỏ về nút cha hiển thị gần nhất.
- Gộp nút nối tiếp cùng vai khi cha chỉ có một con (vd assistant -> tool -> assistant).
- Tuyến chính: đi từ lá đang chọn ngược lên gốc.
- Nhánh anh em được giữ với on_active_path=False.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..schema import Turn
from ..textutil import approx_tokens, detect_lang, has_code


@dataclass
class Node:
    id: str
    role: str                     # "user" | "assistant"
    text: str
    created_at: Optional[float]   # epoch giây, để sắp xếp
    parent: Optional[str]
    order: int = 0                # thứ tự xuất hiện trong file, phá hoà
    children: list[str] = field(default_factory=list)


def _sort_key(n: Node):
    return (n.created_at if n.created_at is not None else float("inf"), n.order)


def build_turns(nodes: dict[str, Node], active_leaf: Optional[str], iso) -> list[Turn]:
    """`iso(epoch)` đổi thời gian sang chuỗi ISO."""
    if not nodes:
        return []
    # cha không tồn tại -> coi là gốc
    for n in nodes.values():
        if n.parent is not None and n.parent not in nodes:
            n.parent = None
        n.children = []
    for n in sorted(nodes.values(), key=_sort_key):
        if n.parent is not None:
            nodes[n.parent].children.append(n.id)

    # Gộp chuỗi cùng vai không phân nhánh
    alias: dict[str, str] = {}
    roots = [n.id for n in sorted(nodes.values(), key=_sort_key) if n.parent is None]
    stack = list(roots)
    while stack:
        nid = stack.pop()
        n = nodes[nid]
        while len(n.children) == 1 and nodes[n.children[0]].role == n.role:
            c = nodes.pop(n.children[0])
            n.text = (n.text + "\n\n" + c.text).strip()
            n.children = c.children
            for gc in n.children:
                nodes[gc].parent = n.id
            alias[c.id] = n.id
        stack.extend(n.children)

    def resolve(x: Optional[str]) -> Optional[str]:
        while x is not None and x in alias:
            x = alias[x]
        return x

    leaf = resolve(active_leaf)
    if leaf is None or leaf not in nodes:
        # mặc định: đi từ gốc mới nhất, luôn theo con mới nhất
        cur = roots and max((r for r in roots if r in nodes), key=lambda r: _sort_key(nodes[r]), default=None)
        while cur and nodes[cur].children:
            cur = max(nodes[cur].children, key=lambda c: _sort_key(nodes[c]))
        leaf = cur

    path: list[str] = []
    cur = leaf
    while cur is not None:
        path.append(cur)
        cur = nodes[cur].parent
    path.reverse()
    on_path = {nid: i for i, nid in enumerate(path)}

    # Độ sâu cho nhánh phụ
    depth: dict[str, int] = {}
    for r in roots:
        if r not in nodes:
            continue
        q = [(r, 0)]
        while q:
            nid, d = q.pop()
            depth[nid] = d
            q.extend((c, d + 1) for c in nodes[nid].children)

    def siblings(n: Node) -> list[str]:
        pool = nodes[n.parent].children if n.parent is not None else [r for r in roots if r in nodes]
        return [s for s in pool if nodes[s].role == n.role]

    turns: list[Turn] = []
    for n in sorted(nodes.values(), key=lambda n: (on_path.get(n.id, depth.get(n.id, 0)), n.id not in on_path, _sort_key(n))):
        sibs = siblings(n)
        turns.append(Turn(
            turn_id=n.id,
            idx=on_path.get(n.id, depth.get(n.id, 0)),
            role=n.role,  # type: ignore[arg-type]
            text=n.text,
            created_at=iso(n.created_at),
            on_active_path=n.id in on_path,
            sibling_count=len(sibs),
            sibling_rank=sibs.index(n.id),
            lang=detect_lang(n.text),  # type: ignore[arg-type]
            n_tokens=approx_tokens(n.text),
            has_code=has_code(n.text),
            parent_id=n.parent,
        ))
    return turns
