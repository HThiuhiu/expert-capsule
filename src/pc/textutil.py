"""Tiện ích văn bản không dùng LLM: ngôn ngữ, đếm token xấp xỉ, có code, chuẩn hoá khoảng trắng."""
from __future__ import annotations

import re

# Ký tự có dấu đặc trưng tiếng Việt (không gồm é/à... chung với tiếng Pháp quá nhiều thì vẫn ổn với dữ liệu VN/EN).
_VI_CHARS = set(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
)
_VI_CHARS |= {c.upper() for c in _VI_CHARS}

# Từ tiếng Việt phổ biến viết không dấu cũng nhận được.
_VI_PLAIN = {
    "anh", "em", "cho", "toi", "minh", "la", "va", "cua", "khong", "nay", "thi", "nhe", "nha",
    "voi", "cac", "nhung", "duoc", "lam", "gi", "sao", "nao", "roi", "di",
}
_EN_STOP = {
    "the", "is", "are", "and", "of", "to", "in", "for", "with", "that", "this", "it", "on",
    "be", "as", "can", "you", "what", "how", "please", "make", "use", "not", "from", "your",
    "an", "or", "if", "do", "does", "should", "would", "will", "my", "we", "i",
}
_FENCE = re.compile(r"```.*?(```|$)", re.S)
_WORD = re.compile(r"[^\W\d_]+", re.U)
_TOKEN = re.compile(r"\w+|[^\w\s]", re.U)
_WS = re.compile(r"\s+")
_CODE_LINE = re.compile(r"^\s*(def |class |import |from \S+ import|function |const |let |var |#include|public |SELECT |\$ |>>> )|[;{}]\s*$", re.M)


def strip_code(text: str) -> str:
    return _FENCE.sub(" ", text)


def detect_lang(text: str) -> str:
    words = _WORD.findall(strip_code(text))
    if not words:
        return "en"
    n = len(words)
    vi = sum(1 for w in words if any(c in _VI_CHARS for c in w))
    vi_plain = sum(1 for w in words if w.lower() in _VI_PLAIN and not any(c in _VI_CHARS for c in w))
    en = sum(1 for w in words if w.lower() in _EN_STOP)
    vi_r = (vi + 0.5 * vi_plain) / n
    en_r = en / n
    if vi_r >= 0.15 and en_r < 0.08:
        return "vi"
    if vi_r < 0.03:
        return "en"
    if vi_r >= 0.35:
        return "vi"
    return "mixed"


def approx_tokens(text: str) -> int:
    """Xấp xỉ: số từ + dấu câu. Đủ cho thống kê và ngưỡng 25 token (B2). Không dùng để tính tiền."""
    return len(_TOKEN.findall(text))


def has_code(text: str) -> bool:
    if "```" in text:
        return True
    return len(_CODE_LINE.findall(text)) >= 3


def norm_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def is_substring(span: str, source: str) -> bool:
    """Kiểm tra chuỗi con sau khi chuẩn hoá khoảng trắng (B3)."""
    s = norm_ws(span)
    return bool(s) and s in norm_ws(source)
