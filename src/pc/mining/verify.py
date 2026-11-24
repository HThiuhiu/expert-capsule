"""B4: pass kiểm chứng (vai `verifier`). Ngữ cảnh: phiên đến lượt cần kiểm cộng 2 lượt sau. Không thấy nhãn labeler."""
from __future__ import annotations

from typing import Optional

from ..schema import Session, Turn
from .common import clip, group
from .label import SYSTEM, _defs, _schema

MAX_CHARS = 28000  # ~6.000 token (D4)


def verify_messages(s: Session, user: Turn, prev_asst: Optional[Turn], note: str = "") -> list[dict]:
    convo = window_text(s, user, prev_asst)
    body = (f"{_defs(False)}\n\n<data>\n{convo}\n</data>\n\nClassify only the turn marked TARGET_USER_TURN "
            "(the turns after it are context to see how the conversation continued). "
            f"Return JSON exactly like: {_schema(False)}")
    if note:
        body += f"\n\nNOTE: {note}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": body}]


def window_text(s: Session, user: Turn, prev_asst: Optional[Turn]) -> str:
    """Phiên đến lượt cần xét cộng 2 lượt sau, cắt theo ngân sách ~6.000 token."""
    path = s.active_turns
    i = next(k for k, t in enumerate(path) if t.turn_id == user.turn_id)
    window = path[: i + 3]
    parts: list[str] = []
    for k, t in enumerate(window):
        if t.turn_id == user.turn_id:
            body = clip(t.text, 8000, 2000)
            tag = ">>> TARGET_USER_TURN <<<"
        elif prev_asst is not None and t.turn_id == prev_asst.turn_id:
            body = clip(t.text, 6000, 2000)
            tag = "PREVIOUS_ASSISTANT_TURN"
        else:
            body = clip(t.text, 1500 if t.role == "user" else 800, 0)
            tag = f"{t.role.upper()} (turn {k}{', after target' if k > i else ''})"
        parts.append(f"[{tag}]\n{body}")
    # Quá dài: bỏ dần lượt cũ ở giữa, giữ lượt đầu
    while sum(map(len, parts)) > MAX_CHARS and len(parts) > 4 and i > 1:
        parts.pop(1)
        i -= 1
    return "\n\n".join(parts)


def confidence(labeler: str, verifier: str) -> str:
    """B4: high nếu trùng nhãn; medium nếu cùng nhóm; dropped nếu khác nhóm."""
    if labeler == verifier:
        return "high"
    if group(labeler) == group(verifier):
        return "medium"
    return "dropped"
