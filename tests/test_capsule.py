"""Test cho Expert Capsule (spec v1.0, Lite). Không gọi LLM: backend giả hoặc dữ liệu tổng hợp."""
import json
from collections import Counter
from pathlib import Path

from capsule import agentq, review
from capsule.common import Batch, ask_many
from capsule.mine import validate
from capsule.package import package
from capsule.package.exports import custom_instructions
from capsule.prefilter import f_praise, score, select
from capsule.quickcheck import pick_holdout
from capsule.synthesize import assign_codes, check_rules, check_style, prefix_for
from pc.config import Config
from pc.llm import LLM
from pc.schema import Session, Turn


def _cfg(tmp: Path, **capsule) -> Config:
    raw = {"paths": {"cache": ".cache/llm", "reports": "reports", "interim": "data/interim"},
           "models": {"cheap": {"model": "agent/x"}, "strong": {"model": "agent/x"}, "judge": {"model": "agent/x"}},
           "capsule": {"owner_name": "An", "slug": "an", "out_dir": "expert", "work_dir": "data/lite", **capsule}}
    (tmp / "reports").mkdir(exist_ok=True)
    return Config(root=tmp, raw=raw)


def _sess(sid: str, created: str, texts: list[tuple[str, str]]) -> Session:
    turns = [Turn(turn_id=f"{sid}:{i}", idx=i, role=r, text=t, created_at=created, on_active_path=True,
                  sibling_count=1, sibling_rank=0, lang="vi", n_tokens=len(t.split()), has_code=False)
             for i, (r, t) in enumerate(texts)]
    return Session(session_id=sid, source="chatgpt", title=sid, created_at=created, n_turns=len(turns), turns=turns)


# ---------- Bước 3 ----------

def test_select_even_split_and_random():
    cands = [{"turn_id": f"{d}{i}", "domain": d, "score": (3 if i < 50 else 0)} for d in "ab" for i in range(80)]
    cands += [{"turn_id": f"c{i}", "domain": "c", "score": 2} for i in range(5)]  # c thiếu ứng viên
    out = select(cands, ["a", "b", "c"], 100, 0.10)
    c = Counter(x["domain"] for x in out)
    assert len(out) == 100
    assert c["c"] == 5 + Counter(x["domain"] for x in out if x["why"] == "random")["c"]
    assert abs(c["a"] - c["b"]) <= 4
    assert Counter(x["why"] for x in out)["random"] == 10
    assert all(x["score"] > 0 for x in out if x["why"] == "score")
    assert out == select(cands, ["a", "b", "c"], 100, 0.10)  # tái lập


def test_score_and_praise():
    assert score({"f_branch": True, "f_lex": True}) == 5
    assert f_praise("Tốt lắm, đúng cách mình muốn chia bước")
    assert not f_praise("ok tốt")


# ---------- Bước 4 ----------

def test_validate_quote_must_be_substring():
    user = "Không phải, ý tôi là   dùng lãi đơn"
    ok = validate({"type": "correct_with_fix", "level": "personal", "quote": "ý tôi là dùng lãi đơn",
                   "aspects": ["correctness", "bogus"]}, user)
    assert ok and ok["aspects"] == ["correctness"]
    assert validate({"type": "correct_with_fix", "level": "personal", "quote": "dùng lãi kép"}, user) is None
    assert validate({"type": "challenge", "level": "weird", "quote": "Không phải"}, user) is None
    assert validate({"type": "none"}, user) == {"type": "none"}


# ---------- Bước 5 ----------

def _evs():
    return {f"E{i}": {"event_id": f"E{i}", "session_id": f"s{i % 3}", "level": "personal" if i % 4 else "universal",
                      "quote": f"q{i}"} for i in range(1, 9)}


def test_check_rules_status_and_blocked():
    evs = _evs()
    raw = [{"when": "a", "do": "Làm x", "events": ["E1", "E2", "E3"]},          # 3 event, 3 phiên
           {"when": "b", "do": "Làm y", "events": ["E3", "E6"]},                # cùng phiên s0 -> ứng viên
           {"when": "c", "do": "Làm z", "events": ["E4", "E8"]},                # universal -> bỏ
           {"when": "d", "do": "Làm w", "events": ["E5", "E7", "BOGUS"]}]
    r = check_rules(raw, evs, blocked=[])
    by = {x["when"]: x for x in r}
    assert by["a"]["status"] == "active" and by["b"]["status"] == "candidate"
    assert "c" not in by and by["d"]["events"] == ["E5", "E7"]
    r2 = check_rules(raw, evs, blocked=[{"E1", "E2"}])
    assert "a" not in {x["when"] for x in r2}


def test_assign_codes_stable():
    used = set()
    p = prefix_for("lap-trinh-thuat-toan", used)
    assert p == "LT" and prefix_for("lap-trinh-ngon-ngu", used) != "LT"
    prev = [{"code": "LT-03", "events": ["E1", "E2", "E3"]}]
    rules = [{"events": ["E9"]}, {"events": ["E1", "E2", "E3", "E4"]}]
    assign_codes(rules, "LT", prev)
    assert rules[1]["code"] == "LT-03" and rules[0]["code"] == "LT-01"
    core = [{"events": ["E1"]}, {"events": ["E7"]}]
    assign_codes(core, "R", [{"code": "R02", "events": ["E7"]}], sep="")
    assert [c["code"] for c in core] == ["R01", "R02"]


def test_check_style_requires_verbatim_example():
    raw = [{"rule": "Trả lời tiếng Việt", "example": "giải thích ngắn thôi"},
           {"rule": "Bịa", "example": "câu không có thật"}]
    out = check_style(raw, ["ok, giải thích   ngắn thôi nhé"], {})
    assert [x["rule"] for x in out] == ["Trả lời tiếng Việt"]


# ---------- Bước 6 ----------

def test_pick_holdout_newest_round_robin():
    by_sid = {f"s{i}": _sess(f"s{i}", f"2026-0{1 + i % 9}-01T00:00:00Z", [("user", "x")]) for i in range(9)}
    evs = [{"event_id": f"E{i}", "session_id": f"s{i}", "domain": "ab"[i % 2], "type": "challenge",
            "level": "personal"} for i in range(9)]
    h = pick_holdout(evs, by_sid, ["a", "b"], 4)
    assert len(h) == 4 and len({e["session_id"] for e in h}) == 4
    assert Counter(e["domain"] for e in h) == Counter({"a": 2, "b": 2})
    assert h[0]["session_id"] == "s8"  # mới nhất của a


# ---------- hàng đợi agent ----------

def test_queue_bundle_import_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    llm = LLM(cfg.path("cache"))
    res = ask_many(llm, {"model": "agent/x"}, ["P1", "P2"], tag="t1")
    res2 = ask_many(llm, {"model": "agent/x"}, ["P3"], tag="t2", system="CAPSULE " * 400)
    assert isinstance(res, Batch) and res.pending == 2 and res2.pending == 1
    paths = agentq.make_bundles(cfg)
    assert len(paths) == 2  # không trộn tag
    txt = paths[1].read_text(encoding="utf-8")
    assert "SHARED BLOCK S1" in txt and agentq.END in txt
    keys = [json.loads(p.read_text(encoding="utf-8"))["key"] for p in agentq.qdir(cfg).glob("*.json")]
    ans = agentq.bdir(cfg) / "t1-00.answers.jsonl"
    ans.write_text("\n".join(json.dumps({"key": k, "answer": {"ok": 1}}) for k in keys) + "\nnot json\n",
                   encoding="utf-8")
    ok, bad, _ = agentq.import_answers(cfg)
    assert ok == 3 and bad == 1 and not list(agentq.qdir(cfg).glob("*.json"))
    again = ask_many(llm, {"model": "agent/x"}, ["P1", "P2"], tag="t1")
    assert again.pending == 0 and again.answers == [{"ok": 1}, {"ok": 1}]


# ---------- Bước 7, 8 ----------

def _synth():
    def rule(code, lvl, ev, sess):
        return {"code": code, "when": "viết lời giải", "do": f"Nêu độ phức tạp ({code}).", "because": "dễ kiểm",
                "scope": "", "exceptions": "", "level": lvl, "events": ev, "sessions": sess, "status": "active"}
    return {"core": [dict(rule("R01", "personal", ["E1", "E2", "E5"], ["s1", "s2"]), members=["LT-01", "TX-01"],
                          domains=["lt", "tx"])],
            "style": [{"rule": "Trả lời bằng tiếng Việt", "example": "giải thích ngắn thôi", "events": []}],
            "holdout_sessions": [], "n_events_train": 6,
            "domains": {
                "lt": {"name": "Thuật toán", "thin": False, "n_sessions": 40, "n_events": 4,
                       "rules": [dict(rule("LT-01", "personal", ["E1", "E2"], ["s1", "s2"]), in_core="R01"),
                                 rule("LT-02", "domain_norm", ["E3", "E4"], ["s3", "s4"])],
                       "candidates": [], "conflicts": [{"events_a": ["E1"], "events_b": ["E3"], "question": "Khi nào A?"}],
                       "cases": [{"event": "E1", "context": "giải bài", "cue": "thiếu", "judgment": "j", "action": "a",
                                  "exception": "", "outcome": "o"}],
                       "playbooks": [{"task_type": "giai-bai", "name": "Giải bài", "n_sessions": 7,
                                      "steps": ["Đọc đề", "Nêu ý tưởng"], "stop_when": "AC", "when_ai_fails": "đòi lại"}],
                       "exemplars": [{"question": "Q?", "answer": "A.", "rules": ["LT-02"]}]},
                "tx": {"name": "Toán", "thin": False, "n_sessions": 30, "n_events": 2,
                       "rules": [dict(rule("TX-01", "personal", ["E5", "E6"], ["s5", "s6"]), in_core="R01")],
                       "candidates": [], "conflicts": [], "cases": [], "playbooks": [], "exemplars": []}}}


def _events():
    return [{"event_id": f"E{i}", "session_id": f"s{i}", "quote": f"Trích dẫn bí mật số {i} dài hơn bốn mươi ký tự nhé",
             "level": "personal", "created_at": "2026-01-01"} for i in range(1, 7)]


def _write_work(cfg, synth):
    from capsule.common import work_dir, write_json, write_jsonl
    wd = work_dir(cfg)
    write_json(wd / "synth.json", synth)
    write_jsonl(wd / "events.jsonl", _events())
    write_json(wd / "quickcheck.json", {"n": 15, "capsule_hits": 9, "base_hits": 4, "models": {}})
    write_json(wd / "domains.json", {"sessions": {"s1": {}, "s2": {}}, "domains": [], "task_types": []})


def test_package_layout_and_privacy(tmp_path):
    cfg = _cfg(tmp_path)
    _write_work(cfg, _synth())
    msg = package(cfg)
    out = tmp_path / "expert" / "expert-an"
    skill = (out / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: expert-an\n") and 'capsule_version: "v1"' in skill
    assert "R01." in skill and "references/domains/lt.md" in skill and "Bạn không phải là An" in skill
    dom = (out / "references" / "domains" / "lt.md").read_text(encoding="utf-8")
    assert "LT-02" in dom and "**LT-01** → R01" in dom  # luật đã lên lõi vẫn giữ bản lĩnh vực, có dấu
    assert "Khi nào A?" in dom and "## Playbook" in dom
    for name in ("exports/custom_instructions.txt", "exports/project_instructions.md", "exports/system_prompt.md"):
        assert (out / name).exists()
    shared = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file() and "private" not in p.parts)
    assert "Trích dẫn bí mật" not in shared
    assert (out / "private" / "evidence.jsonl").exists() and (out / "private" / "events.jsonl").exists()
    meta = json.loads((out / "capsule.json").read_text(encoding="utf-8"))
    assert meta["quickcheck"]["capsule_hits"] == 9 and meta["skill_md"]["within_limits"]
    assert "9/15" in msg
    package(cfg)  # lần hai: tăng phiên bản, lưu bản cũ
    assert (out / "private" / "versions" / "v1" / "SKILL.md").exists()
    assert json.loads((out / "capsule.json").read_text(encoding="utf-8"))["capsule_version"] == "v2"


def test_rule_line_normalizes_llm_text():
    from capsule.package.skill import rule_line
    r = {"when": "Khi người dùng hỏi lại", "do": "Làm đúng việc được hỏi", "because": "Vì Người dùng muốn nhanh"}
    assert rule_line(r) == "Khi người dùng hỏi lại: Làm đúng việc được hỏi. Vì người dùng muốn nhanh."
    assert rule_line({"when": "", "do": "Giữ BFS", "because": "AI hay đổi"}) == "Giữ BFS. Vì AI hay đổi."
    assert rule_line({"when": "x", "do": "Làm y.", "because": "(suy luận)"}) == "Khi x: Làm y."


def test_install_zip_and_dir_exclude_private(tmp_path):
    import zipfile
    from capsule import install
    cfg = _cfg(tmp_path)
    _write_work(cfg, _synth())
    package(cfg)
    z = install.make_zip(cfg)
    names = zipfile.ZipFile(z).namelist()
    assert "expert-an/SKILL.md" in names and "expert-an/references/domains/lt.md" in names
    assert not any("/private/" in n or "/exports/" in n for n in names)
    dest = tmp_path / "skills"
    t = install.install_dir(cfg, dest)
    assert (t / "SKILL.md").exists() and not (t / "private").exists() and (t / install.MARK).exists()
    install.install_dir(cfg, dest)  # cài lại được (thư mục do lệnh này tạo)
    foreign = dest / "expert-an"
    (foreign / install.MARK).unlink()
    import pytest
    with pytest.raises(FileExistsError):
        install.install_dir(cfg, dest)
    assert (tmp_path / "expert" / "expert-an" / "exports" / "HUONG_DAN_CAI.md").exists()


def test_custom_instructions_limit_and_priority():
    s = _synth()
    txt = custom_instructions("An", s, 1500)
    assert len(txt) <= 1501 and "R01" in txt
    short = custom_instructions("An", s, 260)
    assert "LT-02" not in short  # domain_norm bị bỏ trước


def test_review_apply_delete_and_edit(tmp_path):
    cfg = _cfg(tmp_path)
    _write_work(cfg, _synth())
    answers = iter(["x", "b", "s", "", "Làm khác.", "", "q"])  # R01 xoá, LT-01 bỏ qua, LT-02 sửa, dừng
    review.interactive(cfg, ask=lambda _: next(answers), say=lambda *_: None)
    rv = review.load(cfg)
    assert rv["decisions"]["R01"]["action"] == "delete" and rv["deleted"][0]["code"] == "R01"
    s = review.apply(_synth(), rv)
    assert not s["core"] and s["domains"]["lt"]["rules"][1]["do"] == "Làm khác."
    assert s["domains"]["lt"]["rules"][1]["reviewed"]


# ---------- lĩnh vực tuỳ chỉnh ----------

def test_custom_domains_slice_and_relabel(tmp_path):
    from capsule import domains
    from capsule.common import base_dir, write_jsonl
    cfg = _cfg(tmp_path, thin_sessions=2, custom_domains={
        "nc": {"name": "Nghiên cứu", "match": "any", "raw_task": "review paper", "raw_domain": "academic"},
        "swe": {"name": "SWE", "domains": ["lt"], "task_types": ["giai-thich"]}})
    write_jsonl(base_dir(cfg) / "domain_labels.jsonl", [
        {"session_id": "a", "domain_raw": "machine learning", "task_raw": "review paper"},
        {"session_id": "b", "domain_raw": "academic writing", "task_raw": "edit text"},
        {"session_id": "c", "domain_raw": "c++", "task_raw": "explain concept"},
        {"session_id": "d", "domain_raw": "c++", "task_raw": "debug code"}])
    d = {"domains": [{"slug": "lt", "name": "LT", "members": [], "n_sessions": 2, "thin": False}], "task_types": [],
         "sessions": {"a": {"domain": "ml", "task_type": "danh-gia"}, "b": {"domain": "vt", "task_type": "viet"},
                      "c": {"domain": "lt", "task_type": "giai-thich"}, "d": {"domain": "lt", "task_type": "sua-loi"}}}
    x = domains.with_custom(cfg, d)
    assert x["custom_sessions"] == {"nc": ["a", "b"], "swe": ["c"]}
    assert {g["slug"]: g["thin"] for g in x["domains"]} == {"lt": False, "nc": False, "swe": True}
    lab = domains.labels_for(x, ["nc", "swe"])
    assert [lab[s]["domain"] for s in "abcd"] == ["nc", "nc", "swe", "lt"]
    assert lab["a"]["task_type"] == "danh-gia" and d["sessions"]["a"]["domain"] == "ml"  # không sửa bản gốc


# ---------- Bước 1: văn bản dán ----------

def test_paste_parser(tmp_path):
    from pc.ingest import ingest
    p = tmp_path / "gemini.txt"
    p.write_text("=== Ôn DCF ===\nUser: Giải thích DCF\nGemini: DCF là...\ndòng hai\nUser: Không phải, lấy ví dụ VN\n"
                 "Gemini: Ví dụ VNM\n---\nBạn: hi\nAI: hello\n", encoding="utf-8")
    res = ingest(tmp_path, min_user_turns=2)
    assert res.n_raw["gemini"] == 2 and len(res.sessions) == 1 and len(res.dropped_short) == 1
    s = res.sessions[0]
    assert s.source == "gemini" and s.title == "Ôn DCF" and s.n_user_turns == 2
    assert s.active_turns[1].text == "DCF là...\ndòng hai"
