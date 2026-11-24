"""`pc inspect`: soi cấu trúc export thật mà KHÔNG in nội dung (B1: xác nhận cấu trúc trước khi tin parser)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import iter_conversations


def inspect_export(path: Path) -> str:
    files: Counter = Counter()
    kinds: Counter = Counter()
    conv_keys: dict[str, Counter] = {"chatgpt": Counter(), "claude": Counter(), "unknown": Counter()}
    msg_keys: dict[str, Counter] = {"chatgpt": Counter(), "claude": Counter()}
    roles: Counter = Counter()
    ctypes: Counter = Counter()
    part_types: Counter = Counter()
    recipients: Counter = Counter()
    claude_blocks: Counter = Counter()
    senders: Counter = Counter()
    n_conv = {"chatgpt": 0, "claude": 0, "unknown": 0}
    multi_child = 0
    with_parent_uuid = 0

    for fname, conv in iter_conversations(path):
        files[fname] += 1
        if isinstance(conv, dict) and "mapping" in conv:
            k = "chatgpt"
            for node in (conv.get("mapping") or {}).values():
                if len(node.get("children") or []) > 1:
                    multi_child += 1
                m = node.get("message")
                if not m:
                    continue
                msg_keys[k].update(m.keys())
                roles[(m.get("author") or {}).get("role")] += 1
                c = m.get("content") or {}
                ctypes[c.get("content_type")] += 1
                recipients[m.get("recipient")] += 1
                for p in c.get("parts") or []:
                    part_types["str" if isinstance(p, str) else (p.get("content_type") if isinstance(p, dict) else type(p).__name__)] += 1
        elif isinstance(conv, dict) and "chat_messages" in conv:
            k = "claude"
            for m in conv.get("chat_messages") or []:
                msg_keys[k].update(m.keys())
                senders[m.get("sender")] += 1
                if "parent_message_uuid" in m:
                    with_parent_uuid += 1
                for b in m.get("content") or []:
                    if isinstance(b, dict):
                        claude_blocks[b.get("type")] += 1
        else:
            k = "unknown"
        n_conv[k] += 1
        kinds[k] += 1
        if isinstance(conv, dict):
            conv_keys[k].update(conv.keys())

    def fmt(c: Counter, top: int = 30) -> str:
        return ", ".join(f"`{k}`: {v}" for k, v in c.most_common(top)) or "(không có)"

    lines = [f"# Inspect `{path.name}`", "", "Chỉ in khoá và đếm, không in nội dung.", "",
             f"- File: {fmt(files)}", f"- Hội thoại: {n_conv}", ""]
    if n_conv["chatgpt"]:
        lines += ["## ChatGPT", f"- Khoá hội thoại: {fmt(conv_keys['chatgpt'])}",
                  f"- Khoá message: {fmt(msg_keys['chatgpt'])}", f"- author.role: {fmt(roles)}",
                  f"- content_type: {fmt(ctypes)}", f"- kiểu part: {fmt(part_types)}",
                  f"- recipient: {fmt(recipients)}", f"- Nút có >1 con (nhánh): {multi_child}", ""]
    if n_conv["claude"]:
        lines += ["## Claude", f"- Khoá hội thoại: {fmt(conv_keys['claude'])}",
                  f"- Khoá message: {fmt(msg_keys['claude'])}", f"- sender: {fmt(senders)}",
                  f"- Kiểu content block: {fmt(claude_blocks)}",
                  f"- Message có `parent_message_uuid`: {with_parent_uuid}", ""]
    if n_conv["unknown"]:
        lines += ["## Không nhận dạng", f"- Khoá: {fmt(conv_keys['unknown'])}", ""]
    return "\n".join(lines)
