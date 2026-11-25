"""Bước 6: kiểm tra nhanh trên 15 lượt sửa sai giữ lại (phiên mới nhất), không dùng để tổng hợp.

Đưa câu trả lời AI bị sửa cho hai hệ: có capsule (SKILL.md + file lĩnh vực) và không có capsule. Mỗi hệ đưa ra 3 lời
phản biện. Judge đếm bao nhiêu lời phản biện thật của người dùng được bắt trúng (ẩn tên hệ, đảo vị trí theo hash).
Nhỏ và nhiễu: chỉ để có một con số dễ hiểu và phát hiện capsule rỗng ruột. Judge cùng họ với hệ được chấm.
"""
from __future__ import annotations

from collections import defaultdict

from pc.schema import Session

from .common import NeedAgents, ask_many, chunks, clip, role, settings, stable, work_dir, write_json
from .mine import CORRECTIONS, _ctx

BASE_SYSTEM = "You are a helpful assistant."


def pick_holdout(events: list[dict], by_sid: dict[str, Session], chosen: list[str], n: int) -> list[dict]:
    """Chọn n lượt sửa sai từ các phiên mới nhất, xoay vòng theo lĩnh vực, mỗi phiên một lượt."""
    pool = [e for e in events if e["type"] in CORRECTIONS and e["session_id"] in by_sid]
    pool.sort(key=lambda e: (e["level"] == "universal", -_ts(by_sid[e["session_id"]].created_at), e["event_id"]))
    by: dict[str, list[dict]] = defaultdict(list)
    for e in pool:
        by[e["domain"]].append(e)
    for d in by:  # mới nhất trước trong từng lĩnh vực
        by[d].sort(key=lambda e: (-_ts(by_sid[e["session_id"]].created_at), e["level"] == "universal", e["event_id"]))
    out, used = [], set()
    k = 0
    while len(out) < n and any(by.get(d) for d in chosen):
        d = chosen[k % len(chosen)]
        k += 1
        while by.get(d):
            e = by[d].pop(0)
            if e["session_id"] not in used:
                used.add(e["session_id"])
                out.append(e)
                break
    return out


def _ts(iso) -> float:
    from pc.ingest.timeutil import to_epoch
    return to_epoch(iso) or 0.0


def critique_prompt(s: Session, e: dict) -> str:
    _, req, asst, _ = _ctx(s, e["turn_id"])
    return (
        "A user sent the REQUEST below and received the AI_ANSWER. Critique the answer the way this user would: give "
        "exactly 3 short critiques (one sentence each, in the user's language) that this user is most likely to raise, "
        "most likely first.\n\n"
        f"<data>\nREQUEST:\n{clip(req.text, 1500) if req else '(none)'}\n\n"
        f"AI_ANSWER:\n{clip(asst.text, 3000, 800) if asst else '(none)'}\n</data>\n\n"
        "Return JSON exactly like: {\"critiques\": [\"...\", \"...\", \"...\"]}"
    )


def judge_prompt(items: list[dict]) -> str:
    parts = []
    for i, it in enumerate(items):
        parts.append(f"[q{i + 1}]\nTRUE_FEEDBACK (what the user actually said next):\n{clip(it['truth'], 800)}\n"
                     f"LIST_X:\n" + "\n".join(f"  - {c}" for c in it["x"]) +
                     "\nLIST_Y:\n" + "\n".join(f"  - {c}" for c in it["y"]))
    return (
        "For each item, decide whether LIST_X and LIST_Y each contain at least one critique that raises the SAME "
        "point as TRUE_FEEDBACK (same problem or same requested change; wording may differ; a vague generic critique "
        "does not count). Judge X and Y independently.\n\n<data>\n" + "\n\n".join(parts) + "\n</data>\n\n"
        "Return JSON exactly like: {\"items\": [{\"id\": \"q1\", \"x_hit\": true, \"y_hit\": false}, ...]}"
    )


def _crit(d: dict) -> bool:
    c = d.get("critiques")
    return isinstance(c, list) and len(c) >= 1 and all(isinstance(x, str) for x in c)


def run(cfg, llm, sessions: list[Session], holdout: list[dict], capsule_for) -> dict:
    """capsule_for(domain) -> văn bản system prompt của hệ có capsule (SKILL.md + file lĩnh vực)."""
    st = settings(cfg)
    by_sid = {s.session_id: s for s in sessions}
    items = [e for e in holdout if e["session_id"] in by_sid]
    prompts = [critique_prompt(by_sid[e["session_id"]], e) for e in items]
    # mỗi item một lệnh; system khác nhau theo lĩnh vực nên gọi theo nhóm lĩnh vực
    cap_ans: list = [None] * len(items)
    pend = 0
    for d in sorted({e["domain"] for e in items}):
        idx = [i for i, e in enumerate(items) if e["domain"] == d]
        r = ask_many(llm, role(cfg, "strong"), [prompts[i] for i in idx], tag="qc_capsule", workers=st["workers"],
                     check=_crit, system=capsule_for(d), max_tokens=1500)
        pend += r.pending
        for i, a in zip(idx, r.answers):
            cap_ans[i] = a
    base = ask_many(llm, role(cfg, "strong"), prompts, tag="qc_base", workers=st["workers"], check=_crit,
                    system=BASE_SYSTEM, max_tokens=1500)
    pend += base.pending
    if pend:
        raise NeedAgents("Bước 6 (hai hệ phản biện)", pend)
    rows = []
    for e, c, b in zip(items, cap_ans, base.answers):
        if c is None or b is None:
            continue
        cap_first = stable("qc", e["event_id"]) < 0.5
        cc, bc = [str(x) for x in c["critiques"][:3]], [str(x) for x in b["critiques"][:3]]
        truth = _ctx(by_sid[e["session_id"]], e["turn_id"])[3].text
        rows.append({"event_id": e["event_id"], "domain": e["domain"], "truth": truth, "capsule": cc, "base": bc,
                     "cap_is_x": cap_first, "x": cc if cap_first else bc, "y": bc if cap_first else cc})
    groups = chunks(rows, 8)
    jr = ask_many(llm, role(cfg, "judge"), [judge_prompt(g) for g in groups], tag="qc_judge", workers=st["workers"],
                  check=lambda d: isinstance(d.get("items"), list), max_tokens=2000)
    if jr.pending:
        raise NeedAgents("Bước 6 (judge)", jr.pending)
    if rows and jr.errors and not any(jr.answers):
        raise RuntimeError(f"Bước 6: judge lỗi hết ({jr.errors[0][:200]}). Kiểm tra vai `judge` trong config.local.yaml.")
    cap_hits = base_hits = judged = 0
    for g, ans in zip(groups, jr.answers):
        got = {str(x.get("id")): x for x in (ans or {}).get("items") or [] if isinstance(x, dict)}
        for i, r in enumerate(g):
            j = got.get(f"q{i + 1}")
            if not j:
                continue
            x, y = bool(j.get("x_hit")), bool(j.get("y_hit"))
            r["capsule_hit"], r["base_hit"] = (x, y) if r["cap_is_x"] else (y, x)
            cap_hits += r["capsule_hit"]
            base_hits += r["base_hit"]
            judged += 1
    out = {"n": judged, "capsule_hits": cap_hits, "base_hits": base_hits,
           "models": {"systems": role(cfg, "strong")["model"], "judge": role(cfg, "judge")["model"]},
           "items": [{k: v for k, v in r.items() if k not in ("x", "y", "cap_is_x")} for r in rows]}
    write_json(work_dir(cfg) / "quickcheck.json", out)
    return out


def headline(q: dict) -> str:
    if not q or not q.get("n"):
        return "Chưa có kết quả kiểm tra nhanh."
    return (f"Capsule bắt đúng {q['capsule_hits']}/{q['n']} lần bạn từng sửa AI, so với "
            f"{q['base_hits']}/{q['n']} khi không có capsule.")
