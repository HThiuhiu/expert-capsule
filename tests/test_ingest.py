import json
from collections import Counter

from fixtures import chatgpt_branched, chatgpt_merge, chatgpt_short, claude_flat, claude_tree
from pc.ingest import ingest, read_sessions, write_sessions
from pc.ingest import chatgpt, claude
from pc.reports.step0 import render


def by_id(s):
    return {t.turn_id: t for t in s.turns}


def test_chatgpt_branch_linearization():
    s = chatgpt.parse_conversation(chatgpt_branched())
    path = [t.turn_id for t in s.active_turns]
    assert path == ["u1", "a1", "u2b", "a2b", "u3", "a3"]
    assert [t.idx for t in s.active_turns] == list(range(6))
    assert s.n_turns == 6 and s.n_user_turns == 3
    T = by_id(s)
    # ẩn: system, custom instructions, tool call, tool output, thoughts
    for hidden in ("sys", "ctx", "call", "tool", "think"):
        assert hidden not in T
    # nhánh sửa prompt
    assert not T["u2a"].on_active_path and not T["a2a"].on_active_path
    assert (T["u2a"].sibling_count, T["u2a"].sibling_rank) == (2, 0)
    assert (T["u2b"].sibling_count, T["u2b"].sibling_rank) == (2, 1)
    # regenerate: a2c là anh em cũ của a2b (sau khi bỏ nút tool)
    assert T["a2b"].parent_id == "u2b" and T["a2c"].parent_id == "u2b"
    assert not T["a2c"].on_active_path
    assert T["a2b"].sibling_count == 2 and T["a2c"].sibling_rank == 0
    # u1 có cha ẩn -> là gốc
    assert T["u1"].parent_id is None
    assert T["a3"].parent_id == "u3"
    assert s.has_branch
    assert s.created_at.endswith("Z")


def test_chatgpt_merges_consecutive_assistant():
    s = chatgpt.parse_conversation(chatgpt_merge())
    assert [t.turn_id for t in s.active_turns] == ["u1", "a1", "u2", "a2"]
    a1 = by_id(s)["a1"]
    assert "Đang tìm." in a1.text and "Giá vàng là X." in a1.text
    assert by_id(s)["u2"].parent_id == "a1"
    assert not s.has_branch


def test_claude_flat():
    c = Counter()
    s = claude.parse_conversation(claude_flat(), c)
    assert [t.role for t in s.active_turns] == ["user", "assistant", "user", "assistant"]
    T = by_id(s)
    assert "[attachment: spec.md]" in T["m1"].text
    assert T["m2"].text == "Spec ổn, nhưng thiếu phần eval."  # bỏ thinking, tool_use
    assert "[EMAIL]" in T["m3"].text and "example.com" not in T["m3"].text
    assert c["EMAIL"] == 1
    assert T["m3"].parent_id == "m2"
    assert all(t.on_active_path for t in s.turns)


def test_claude_tree_latest_leaf():
    s = claude.parse_conversation(claude_tree())
    assert [t.turn_id for t in s.active_turns] == ["h1", "x1", "h2b", "x2b"]
    T = by_id(s)
    assert not T["h2a"].on_active_path
    assert T["h2b"].sibling_count == 2 and T["h2b"].sibling_rank == 1


def test_ingest_filters_and_roundtrip(tmp_path):
    raw = tmp_path / "raw"
    (raw / "gpt").mkdir(parents=True)
    (raw / "claude").mkdir()
    (raw / "gpt" / "conversations.json").write_text(
        json.dumps([chatgpt_branched(), chatgpt_merge(), chatgpt_short()], ensure_ascii=False), encoding="utf-8")
    (raw / "claude" / "conversations.json").write_text(
        json.dumps([claude_flat(), claude_tree(), {"foo": 1}], ensure_ascii=False), encoding="utf-8")
    (raw / "claude" / "users.json").write_text("[]", encoding="utf-8")  # phải bị bỏ qua

    res = ingest(raw)
    assert res.n_raw == {"chatgpt": 3, "claude": 2}
    assert res.n_unknown == 1
    assert len(res.sessions) == 4 and len(res.dropped_short) == 1  # chatgpt_short chỉ 1 lượt user
    assert not res.errors

    out = tmp_path / "sessions.jsonl"
    write_sessions(res.sessions, out)
    back = read_sessions(out)
    assert [s.to_dict() for s in back] == [s.to_dict() for s in res.sessions]

    rep = render(res, gate_min=300)
    assert "CHƯA ĐẠT" in rep and "4 phiên" in rep
    assert render(res, gate_min=4).count("**ĐẠT**") == 1


def test_ingest_zip(tmp_path):
    import zipfile
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("conversations.json", json.dumps([chatgpt_branched()]))
    res = ingest(z)
    assert len(res.sessions) == 1
