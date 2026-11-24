"""B2: đặc trưng tiền lọc rẻ, không dùng LLM. Không lọc cứng; chỉ là đầu vào phụ và để lấy mẫu phân tầng.

`f_rephrase` cần embedding đa ngôn ngữ (bge-m3). Chưa cài thì để None.
"""
from __future__ import annotations

import re
from typing import Optional

from ..schema import Session, Turn
from ..textutil import approx_tokens, strip_code

_LEX = [
    # tiếng Việt
    "không phải", "sai", "chưa đúng", "ý tôi là", "ý mình là", "làm lại", "thay vì", "đừng", "thiếu",
    "không đúng", "nhầm", "chưa được", "vẫn lỗi", "vẫn chưa", "không ổn", "tệ", "lại bị", "không chạy",
    # tiếng Anh
    "no,", "wrong", "actually", "instead", "not what", "doesn't work", "still", "incorrect", "i meant",
]
_LEX_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in _LEX) + r")(?![\w])", re.I)

_IMPERATIVE = {
    "hãy", "viết", "sửa", "làm", "thêm", "bỏ", "xoá", "xóa", "đổi", "cho", "giúp", "tạo", "giải", "kiểm",
    "dùng", "chỉnh", "đừng", "tìm", "vẽ", "chạy", "check", "fix", "add", "remove", "make", "write", "use",
    "give", "show", "explain", "try", "don't", "do", "change", "rewrite", "redo", "keep", "stop",
}
_FIRST = re.compile(r"[^\W\d_][\w']*", re.U)


def f_lex(text: str) -> bool:
    return bool(_LEX_RE.search(strip_code(text)))


def f_short_imperative(text: str) -> bool:
    if approx_tokens(text) >= 25:
        return False
    m = _FIRST.search(text.strip())
    return bool(m) and m.group(0).lower() in _IMPERATIVE


def features(session: Session, user: Turn, prev_asst: Optional[Turn], rephrase: Optional[bool] = None) -> dict:
    branch = user.sibling_count > 1 or (prev_asst is not None and prev_asst.sibling_count > 1)
    return {"f_branch": branch, "f_lex": f_lex(user.text), "f_short_imperative": f_short_imperative(user.text),
            "f_rephrase": rephrase}
