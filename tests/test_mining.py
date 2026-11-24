import json

import pytest

from pc.llm import LLM, Pending
from pc.mining.assemble import session_events
from pc.mining.common import parse_json
from pc.mining.label import call_with_check, turn_messages
from pc.mining.prefilter import f_lex, f_short_imperative
from pc.mining.verify import confidence
from pc.schema import Session, Turn


def T(tid, idx, role, text, parent=None, on=True, sib=1, rank=0):
    return Turn(turn_id=tid, idx=idx, role=role, text=text, created_at=f"2026-01-01T00:00:{idx:02d}Z",
                on_active_path=on, sibling_count=sib, sibling_rank=rank, lang="vi", n_tokens=5, has_code=False,
                parent_id=parent)


def chain_session():
    return Session("s1", "claude", "t", "2026-01-01T00:00:00Z", 8, [
        T("u0", 0, "user", "Viết hàm tính lãi kép"),
        T("a0", 1, "assistant", "def f(): lãi kép", "u0"),
        T("u1", 2, "user", "Sai rồi, thiếu phí giao dịch", "a0"),
        T("a1", 3, "assistant", "def f(): có phí", "u1"),
        T("u2", 4, "user", "Vẫn chưa đúng, phí tính theo tháng", "a1"),
        T("a2", 5, "assistant", "def f(): phí theo tháng", "u2"),
        T("u3", 6, "user", "Tốt, giờ vẽ biểu đồ", "a2"),
        T("a3", 7, "assistant", "plot", "u3"),
        T("a3x", 7, "assistant", "plot cũ", "u3", on=False, sib=2, rank=0),  # regenerate
    ])


def L(p):
    return {"label": {"primary_label": p, "aspects": [], "generalizability": "task_type", "idiosyncrasy": "personal",
                      "evidence_span": "x", "target_span": ""}, "confidence": "high"}


def test_request_and_outcome_in_multi_round_chain():
    s = chain_session()
    final = {"u0": {"label": None, "confidence": "n/a"}, "u1": L("correct_with_fix"), "u2": L("correct_with_fix"),
             "u3": L("accept_build_on")}
    ev, fs = session_events(s, final, {"task_type": "build_code", "domain": "quant_finance"})
    by = {e["event_id"]: e for e in ev}
    e1, e2 = by["ev:u1"], by["ev:u2"]
    assert e1["turns"] == {"request": "u0", "rejected": "a0", "feedback": "u1", "revised": "a1", "outcome_turn": "u2"}
    assert e1["outcome"] == "corrected_again" and e1["chain_pos"] == 0
    assert e2["turns"]["request"] == "u0" and e2["turns"]["rejected"] == "a1"  # đi ngược qua lượt sửa u1
    assert e2["outcome"] == "accepted_implicit" and e2["chain_pos"] == 1 and e2["chain_id"] == e1["chain_id"]
    assert e1["task"]["request_text"] == "Viết hàm tính lãi kép"
    # regenerate
    rg = by["ev:regen:a3x"]
    assert rg["rejected_text"] == "plot cũ" and rg["revised_text"] == "plot" and rg["feedback_text"] == ""
    assert rg["feedback"]["primary_label"] == "rephrase_retry" and rg["outcome"] == "abandoned"
    assert fs == []  # a0 bị sửa ngay; a3 không có phản hồi


def test_outcome_variants_and_firstshot():
    s = chain_session()
    final = {"u0": {"label": None, "confidence": "n/a"}, "u1": L("challenge"),
             "u2": L("accept_explicit"), "u3": L("accept_build_on")}
    ev, fs = session_events(s, final, {})
    assert [e["outcome"] for e in ev if e["event_id"] == "ev:u1"] == ["accepted_explicit"]
    # u2 (accept_explicit) là yêu cầu không-sửa-sai -> a2 được nhận ngay bởi u3
    assert [(f["request_turn"], f["answer_turn"], f["accept_label"]) for f in fs] == [("u2", "a2", "accept_build_on")]
    # nhãn dropped -> outcome unknown, không tạo event
    final["u2"] = {"label": None, "confidence": "dropped"}
    ev, _ = session_events(s, final, {})
    assert [e["outcome"] for e in ev if e["event_id"] == "ev:u1"] == ["unknown"]
    assert "ev:u2" not in {e["event_id"] for e in ev}


def _fake(answers):
    calls = []

    def backend(model, messages, **params):
        calls.append(messages[-1]["content"])
        return {"text": answers[min(len(calls) - 1, len(answers) - 1)], "input_tokens": 1, "output_tokens": 1}
    return backend, calls


GOOD = {"primary_label": "correct_with_fix", "move": "refine", "aspects": ["correctness", "bogus"],
        "generalizability": "task_type", "idiosyncrasy": "personal", "evidence_span": "thiếu   phí",
        "target_span": "lãi kép", "has_assertion": True}


def test_label_span_retry_then_ok(tmp_path):
    s = chain_session()
    u, a = s.turns[2], s.turns[1]
    bad = dict(GOOD, evidence_span="thiếu thuế")  # không phải chuỗi con
    backend, calls = _fake([json.dumps(bad), "```json\n" + json.dumps(GOOD) + "\n```"])
    lab, status = call_with_check(LLM(tmp_path, backend), {"model": "m"}, lambda n: turn_messages(s.turns[0], a, u, n), u, a)
    assert status == "retried" and len(calls) == 2 and "NOTE" in calls[1]
    assert lab["primary_label"] == "correct_with_fix" and lab["aspects"] == ["correctness"]


def test_label_downgrade_and_invalid(tmp_path):
    s = chain_session()
    u, a = s.turns[2], s.turns[1]
    bad = dict(GOOD, target_span="không có trong câu trả lời")
    backend, _ = _fake([json.dumps(bad)])
    lab, status = call_with_check(LLM(tmp_path / "a", backend), {"model": "m"},
                                  lambda n: turn_messages(None, a, u, n), u, a)
    assert status == "downgraded" and lab["primary_label"] == "other" and lab["move"] == "refine"
    backend, _ = _fake(["not json"])
    lab, status = call_with_check(LLM(tmp_path / "b", backend), {"model": "m"},
                                  lambda n: turn_messages(None, a, u, n), u, a)
    assert status == "invalid" and lab["primary_label"] == "other"


def test_confidence_rule():
    assert confidence("challenge", "challenge") == "high"
    assert confidence("challenge", "constraint_add") == "medium"
    assert confidence("challenge", "followup_info") == "dropped"


def test_agent_queue_roundtrip(tmp_path):
    llm = LLM(tmp_path / "llm")
    msgs = [{"role": "user", "content": "x"}]
    with pytest.raises(Pending) as e:
        llm.complete({"model": "agent/claude-haiku"}, msgs)
    key = str(e.value)
    assert (llm.queue_dir / f"{key}.json").exists()
    ans = tmp_path / "ans.jsonl"
    ans.write_text(json.dumps({"key": key, "text": "{\"a\": 1}"}) + "\n", encoding="utf-8")
    assert llm.import_answers(ans) == 1
    assert not (llm.queue_dir / f"{key}.json").exists()
    assert llm.complete({"model": "agent/claude-haiku"}, msgs) == "{\"a\": 1}"


def test_prefilter_and_json():
    assert f_lex("Không phải, ý tôi là dùng lãi đơn") and not f_lex("Cảm ơn, rất tốt")
    assert f_short_imperative("Viết lại ngắn hơn") and not f_short_imperative("Tôi nghĩ là ổn")
    assert parse_json('trước {"a": 1} sau') == {"a": 1} and parse_json("[1]") is None


def test_gold_sample_and_stratified_recall():
    from pc.mining.gold import sample, score

    def row(i, lab, conf, feat):
        return {"turn_id": f"t{i}", "session_id": "s", "labeler": {"primary_label": lab},
                "confidence": conf, "features": {"f_branch": False, "f_lex": feat}}
    rows = [row(i, "challenge", "high", False) for i in range(10)]          # S1: N=10
    rows += [row(10 + i, "followup_info", "n/a", True) for i in range(20)]   # S2: N=20
    rows += [row(30 + i, "other", "n/a", False) for i in range(100)]         # S3: N=100
    rows += [row(200, "challenge", "dropped", False)]                       # dropped -> không phải Sửa sai
    S = sample(rows)
    by = {}
    for s in S:
        by.setdefault(s["stratum"], []).append(s)
    assert len(by["S1_correction"]) == 10 and len(by["S2_noncorr_feat"]) == 20 and len(by["S3_noncorr_rand"]) == 50
    assert by["S3_noncorr_rand"][0]["N_stratum"] == 101
    # gold: S1 đúng 8/10; S2 có 4/20 là Sửa sai; S3 có 0
    s1 = [s["turn_id"] for s in by["S1_correction"]]
    s2 = [s["turn_id"] for s in by["S2_noncorr_feat"]]
    gold = [{"turn_id": t, "primary_label": "challenge" if k < 8 else "other", "annotator": "x"} for k, t in enumerate(s1)]
    gold += [{"turn_id": t, "primary_label": "reject_no_fix" if k < 4 else "other", "annotator": "x"} for k, t in enumerate(s2)]
    gold += [{"turn_id": s["turn_id"], "primary_label": "other", "annotator": "x"} for s in by["S3_noncorr_rand"]]
    _, res = score(S, gold, {r["turn_id"]: r for r in rows}, [], "x")
    assert abs(res["precision"]["high"][0] - 0.8) < 1e-9
    assert abs(res["recall"] - 8 / (8 + 4)) < 1e-9   # TP = 10*0.8, FN = 20*0.2 + 101*0
