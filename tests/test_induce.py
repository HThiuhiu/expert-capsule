import json

from pc.induce.consolidate import _valid, consolidate, nearest
from pc.induce.lesson import induce_one
from pc.induce.render import skill_md, summary
from pc.induce.split import split_sessions
from pc.llm import LLM

TT = ["build_code", "debug_fix", "other"]


def test_split_by_time_and_ratio():
    ss = [(f"s{i}", f"2026-01-{i + 1:02d}T00:00:00Z") for i in range(10)][::-1]
    sp = split_sessions(ss)
    assert [sp[f"s{i}"] for i in range(10)] == ["train"] * 7 + ["dev"] + ["test"] * 2


def EV(eid="ev:1", sid="s1", at="2026-01-01T00:00:00Z"):
    return {"event_id": eid, "session_id": sid, "created_at": at, "outcome": "accepted_implicit",
            "task": {"request_text": "viết hàm", "task_type": "build_code", "domain": "software_web"},
            "rejected_text": "Đây là hàm dài 200 dòng không có test.", "feedback_text": "ngắn thôi, thêm test",
            "revised_text": "hàm ngắn + test",
            "feedback": {"primary_label": "constraint_add", "aspects": ["scope_depth"], "generalizability": "task_type",
                         "idiosyncrasy": "personal", "evidence_span": "thêm test", "target_span": ""}}


def fake_llm(tmp_path, answers):
    it = iter(answers)
    return LLM(tmp_path, backend=lambda model, messages, **p: {"text": next(it), "input_tokens": 1, "output_tokens": 1})


def lesson(cue_span="không có test", when="khi viết hàm"):
    return json.dumps({"case": {"context": "viết hàm", "cue": "thiếu test", "cue_span": cue_span, "judgment": "chưa đạt",
                                "action": "thêm test", "boundary": ""},
                       "rule": {"when": when, "do_or_dont": "Làm: kèm unit test", "because": "(suy luận) muốn kiểm được",
                                "aspects": ["scope_depth", "bogus"], "task_types": ["build_code", "nope"],
                                "exclusive": True}}, ensure_ascii=False)


def test_lesson_validates_and_drops_fake_cue_span(tmp_path):
    llm = fake_llm(tmp_path, [lesson(cue_span="câu không có trong câu trả lời")])
    case, cand, st = induce_one(llm, {"model": "x/y"}, EV(), TT)
    assert st == "ok" and case["cue_span"] == "" and case["evidence"][0] == "thêm test"
    assert cand["aspects"] == ["scope_depth"] and cand["task_types"] == ["build_code"]
    assert cand["source_event_id"] == "ev:1" and cand["idiosyncrasy"] == "personal"


def test_lesson_retries_then_invalid(tmp_path):
    llm = fake_llm(tmp_path, ["not json", "{}"])
    case, cand, st = induce_one(llm, {"model": "x/y"}, EV(), TT)
    assert (case, cand, st) == (None, None, "invalid")


def C(eid, sid, at, when="khi viết hàm python", do="Làm: kèm unit test", idio="personal", ex=True):
    return {"when": when, "do_or_dont": do, "because": "", "aspects": [], "task_types": ["build_code"],
            "exclusive": ex, "idiosyncrasy": idio, "source_event_id": eid, "session_id": sid, "created_at": at}


def merge_first(cand, neigh):
    return {"op": "MERGE_INTO", "rule_id": neigh[0]["rule_id"], "new_when": "", "reason": ""}


def test_merge_makes_supported_only_with_two_sessions():
    cands = [C("e1", "s1", "2026-01-01"), C("e2", "s1", "2026-01-02"), C("e3", "s1", "2026-01-03")]
    rules, deltas, _ = consolidate(cands, merge_first)
    assert len(rules) == 1 and rules[0]["status"] == "candidate"  # 3 event nhưng 1 phiên
    rules, _, _ = consolidate(cands + [C("e4", "s2", "2026-01-04")], merge_first)
    assert rules[0]["status"] == "supported" and rules[0]["n_sessions"] == 2
    assert [d["op"] for d in deltas] == ["ADD", "MERGE_INTO", "MERGE_INTO"]


def test_conflict_recent_goes_to_questions_old_is_superseded():
    conflict = lambda c, n: {"op": "CONFLICT_WITH", "rule_id": n[0]["rule_id"], "new_when": "", "reason": "trái"}
    rules, _, qs = consolidate([C("e1", "s1", "2026-01-01T00:00:00Z"), C("e2", "s2", "2026-02-01T00:00:00Z",
                                                                         do="Không: viết test")], conflict)
    assert [r["status"] for r in rules] == ["conflicted", "conflicted"] and len(qs) == 1
    rules, _, qs = consolidate([C("e1", "s1", "2026-01-01T00:00:00Z"), C("e2", "s2", "2026-06-01T00:00:00Z",
                                                                         do="Không: viết test")], conflict)
    assert rules[0]["status"] == "superseded" and rules[0]["superseded_by"] == "r002" and not qs
    assert rules[1]["status"] == "candidate"


def test_narrow_scope_keeps_history_and_adds_rule():
    narrow = lambda c, n: {"op": "NARROW_SCOPE", "rule_id": n[0]["rule_id"], "new_when": "khi viết hàm python cho prod",
                           "reason": ""}
    rules, _, _ = consolidate([C("e1", "s1", "2026-01-01"), C("e2", "s2", "2026-01-02")], narrow)
    assert rules[0]["when"] == "khi viết hàm python cho prod" and rules[0]["scope_history"][0]["from"] == "khi viết hàm python"
    assert len(rules) == 2


def test_unrelated_candidate_skips_llm_and_nearest_ignores_superseded():
    called = []
    rules, deltas, _ = consolidate([C("e1", "s1", "1", when="khi viết hàm"), C("e2", "s2", "2", when="soạn email")],
                                   lambda c, n: called.append(1) or merge_first(c, n))
    # cùng task_type nên vẫn có lân cận; đổi task_type để chắc chắn không gọi
    c3 = {**C("e3", "s3", "3", when="giải đề toán"), "task_types": ["other"]}
    assert nearest(rules, c3) == []
    rules[0]["status"] = "superseded"
    assert all(r["rule_id"] != "r001" for r in nearest(rules, C("e4", "s4", "4", when="khi viết hàm")))


def test_valid_rejects_unknown_rule_id():
    assert _valid({"op": "MERGE_INTO", "rule_id": "r999"}, {"r001"}) is None
    assert _valid({"op": "NARROW_SCOPE", "rule_id": "r001", "new_when": ""}, {"r001"}) is None
    assert _valid({"op": "ADD"}, set())["op"] == "ADD"


def test_render_summary_limit_and_generic_excluded():
    cands = [C(f"e{i}", f"s{i % 2}", f"2026-01-{i + 1:02d}") for i in range(4)]
    rules, _, _ = consolidate(cands, merge_first)
    g = consolidate([C("g1", "s1", "1", ex=False), C("g2", "s2", "2", ex=False), C("g3", "s3", "3", ex=False)],
                    merge_first)[0][0]
    g["rule_id"] = "r099"
    md = skill_md(rules + [g], "cap", 7, TT)
    assert md.startswith("---\nname: cap") and "r001" in md and "r099" not in md
    assert "1 quy tắc bị loại" in md
    assert len(summary(rules * 200, max_chars=300)) <= 300
