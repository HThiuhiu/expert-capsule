"""Che bí mật và PII bằng regex trước mọi lệnh gọi LLM (B1).

Chạy ngay lúc ingest, nên mọi file trong data/interim đã được che. Mọi kiểm tra chuỗi con về sau
đều so với văn bản đã che, nên vẫn nhất quán.
"""
from __future__ import annotations

import re
from collections import Counter

# Thứ tự quan trọng: key cụ thể trước, mẫu chung sau.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("API_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("API_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("API_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API_KEY", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("API_KEY", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("API_KEY", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("API_KEY", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("API_KEY", re.compile(r"\b(?:hf|glpat|npm|pypi|rk_live|sk_live|pk_live)_[A-Za-z0-9_\-]{20,}")),
    ("API_KEY", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),  # JWT
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    # key=value cho secret chung: giữ tên khoá, che giá trị
    ("SECRET", re.compile(
        r"(?i)(\b(?:api[_\-]?key|secret|token|access[_\-]?key|client[_\-]?secret|password|passwd|pwd|"
        r"mật\s*khẩu|mat\s*khau|pass)\b\s*[:=]\s*[\"']?)([^\s\"',;]{4,})"
    )),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # SĐT VN: 0xxxxxxxxx, +84xxxxxxxxx, có thể có dấu cách/chấm/gạch
    ("PHONE", re.compile(r"(?<![\w.])(?:\+?84|0)(?:[\s.\-]?\d){9,10}(?![\w.])")),
    # SĐT quốc tế dạng +CC ...
    ("PHONE", re.compile(r"(?<![\w.])\+\d{1,3}[\s.\-]?\(?\d{2,4}\)?(?:[\s.\-]?\d{2,4}){2,4}(?![\w.])")),
]


def scrub(text: str, counter: Counter | None = None) -> str:
    for label, pat in _PATTERNS:
        if label == "SECRET":
            def _rep(m: re.Match, _l=label) -> str:
                if counter is not None:
                    counter[_l] += 1
                return m.group(1) + f"[{_l}]"
        else:
            def _rep(m: re.Match, _l=label) -> str:
                if counter is not None:
                    counter[_l] += 1
                return f"[{_l}]"
        text = pat.sub(_rep, text)
    return text
