"""Schema chuẩn (B1). Thêm `parent_id` vào Turn: cần cho B5 (nhánh regenerate)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

Role = Literal["user", "assistant"]
Lang = Literal["vi", "en", "mixed"]


@dataclass
class Turn:
    turn_id: str
    idx: int                      # vị trí trên tuyến chính; với nhánh phụ là độ sâu trong cây
    role: Role
    text: str
    created_at: Optional[str]
    on_active_path: bool
    sibling_count: int            # số anh em cùng vai (kể cả chính nó)
    sibling_rank: int             # thứ tự theo thời gian trong nhóm anh em, 0-based
    lang: Lang
    n_tokens: int
    has_code: bool
    parent_id: Optional[str] = None


@dataclass
class Session:
    session_id: str
    source: Literal["chatgpt", "claude", "gemini"]
    title: str
    created_at: Optional[str]
    n_turns: int                  # số lượt trên tuyến chính
    turns: list[Turn] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Session":
        turns = [Turn(**t) for t in d.get("turns", [])]
        return Session(**{**d, "turns": turns})

    @property
    def active_turns(self) -> list[Turn]:
        return sorted((t for t in self.turns if t.on_active_path), key=lambda t: t.idx)

    @property
    def n_user_turns(self) -> int:
        return sum(1 for t in self.active_turns if t.role == "user")

    @property
    def has_branch(self) -> bool:
        return any(not t.on_active_path for t in self.turns) or any(t.sibling_count > 1 for t in self.turns)
