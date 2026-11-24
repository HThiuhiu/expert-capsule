"""Export giả lập theo cấu trúc hiểu biết hiện có. Không thay được việc soi file thật (`pc inspect`)."""
from __future__ import annotations


def _msg(mid, role, text, t, ctype="text", recipient="all", hidden=False):
    content = {"content_type": ctype}
    if ctype == "code":
        content["text"] = text
    else:
        content["parts"] = [text]
    return {"id": mid, "author": {"role": role}, "create_time": t, "content": content,
            "recipient": recipient, "metadata": {"is_visually_hidden_from_conversation": hidden}}


def _tree(conv_id, nodes, current, title="t", t0=1_700_000_000):
    """nodes: list (id, parent, message|None)."""
    mapping = {}
    for nid, parent, msg in nodes:
        mapping[nid] = {"id": nid, "parent": parent, "children": [], "message": msg}
    for nid, parent, _ in nodes:
        if parent:
            mapping[parent]["children"].append(nid)
    return {"id": conv_id, "conversation_id": conv_id, "title": title, "create_time": t0,
            "mapping": mapping, "current_node": current}


def chatgpt_branched():
    t = 1_700_000_000
    return _tree("c1", [
        ("root", None, None),
        ("sys", "root", _msg("sys", "system", "", t, hidden=True)),
        ("ctx", "sys", _msg("ctx", "user", "custom instr", t, ctype="user_editable_context")),
        ("u1", "ctx", _msg("u1", "user", "Viết hàm tính lãi kép giúp tôi", t + 1)),
        ("a1", "u1", _msg("a1", "assistant", "Đây là hàm tính lãi kép ...", t + 2)),
        ("u2a", "a1", _msg("u2a", "user", "Sai rồi, dùng lãi đơn", t + 3)),          # bản sửa cũ
        ("a2a", "u2a", _msg("a2a", "assistant", "OK lãi đơn ...", t + 4)),
        ("u2b", "a1", _msg("u2b", "user", "Không phải, thiếu phí giao dịch", t + 5)),  # bản sửa mới, tuyến chính
        ("a2c", "u2b", _msg("a2c", "assistant", "Bản cũ bị regenerate", t + 6)),
        ("call", "u2b", _msg("call", "assistant", "print(1)", t + 7, ctype="code", recipient="python")),
        ("tool", "call", _msg("tool", "tool", "1", t + 8, ctype="execution_output")),
        ("a2b", "tool", _msg("a2b", "assistant", "Đã thêm phí giao dịch ...", t + 9)),
        ("u3", "a2b", _msg("u3", "user", "Tốt, giờ viết test", t + 10)),
        ("think", "u3", _msg("think", "assistant", "...", t + 11, ctype="thoughts")),
        ("a3", "think", _msg("a3", "assistant", "def test_...", t + 12)),
    ], current="a3", title="Lãi kép")


def chatgpt_merge():
    t = 1_700_100_000
    return _tree("c2", [
        ("root", None, None),
        ("u1", "root", _msg("u1", "user", "Tìm giá vàng hôm nay", t + 1)),
        ("a1", "u1", _msg("a1", "assistant", "Đang tìm.", t + 2)),
        ("call", "a1", _msg("call", "assistant", "search(...)", t + 3, ctype="code", recipient="web")),
        ("tool", "call", _msg("tool", "tool", "...", t + 4)),
        ("a1b", "tool", _msg("a1b", "assistant", "Giá vàng là X.", t + 5)),
        ("u2", "a1b", _msg("u2", "user", "Nguồn đâu?", t + 6)),
        ("a2", "u2", _msg("a2", "assistant", "Nguồn: ...", t + 7)),
    ], current="a2")


def chatgpt_short():
    t = 1_700_200_000
    return _tree("c3", [
        ("root", None, None),
        ("u1", "root", _msg("u1", "user", "hi", t + 1)),
        ("a1", "u1", _msg("a1", "assistant", "hello", t + 2)),
    ], current="a1")


def claude_flat():
    return {
        "uuid": "k1", "name": "Spec review", "created_at": "2026-10-01T08:00:00.000000Z",
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "text": "Review spec này", "created_at": "2026-10-01T08:00:01Z",
             "content": [{"type": "text", "text": "Review spec này"}],
             "attachments": [{"file_name": "spec.md", "extracted_content": "# Spec\nnội dung"}], "files": []},
            {"uuid": "m2", "sender": "assistant", "text": "", "created_at": "2026-10-01T08:00:02Z",
             "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "tool_use", "name": "x"},
                         {"type": "text", "text": "Spec ổn, nhưng thiếu phần eval."}]},
            {"uuid": "m3", "sender": "human", "text": "Chưa đúng, thiếu baseline. Email tôi: a.b@example.com",
             "created_at": "2026-10-01T08:00:03Z", "content": []},
            {"uuid": "m4", "sender": "assistant", "text": "Đã thêm baseline.", "created_at": "2026-10-01T08:00:04Z"},
        ],
    }


def claude_tree():
    R = "00000000-0000-4000-8000-000000000000"
    return {
        "uuid": "k2", "name": "Branch", "created_at": "2026-10-02T08:00:00Z",
        "chat_messages": [
            {"uuid": "h1", "parent_message_uuid": R, "sender": "human", "text": "Giải thích DCF", "created_at": "2026-10-02T08:00:01Z"},
            {"uuid": "x1", "parent_message_uuid": "h1", "sender": "assistant", "text": "DCF là ...", "created_at": "2026-10-02T08:00:02Z"},
            {"uuid": "h2a", "parent_message_uuid": "x1", "sender": "human", "text": "Ví dụ đi", "created_at": "2026-10-02T08:00:03Z"},
            {"uuid": "x2a", "parent_message_uuid": "h2a", "sender": "assistant", "text": "Ví dụ ...", "created_at": "2026-10-02T08:00:04Z"},
            {"uuid": "h2b", "parent_message_uuid": "x1", "sender": "human", "text": "Đừng dùng ví dụ Mỹ, lấy VN", "created_at": "2026-10-02T08:00:05Z"},
            {"uuid": "x2b", "parent_message_uuid": "h2b", "sender": "assistant", "text": "Ví dụ VNM ...", "created_at": "2026-10-02T08:00:06Z"},
        ],
    }
