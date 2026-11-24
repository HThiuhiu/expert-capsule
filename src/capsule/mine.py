"""Bước 4: khai thác (LLM rẻ, theo lô khoảng 10 lượt) và gán move cho chuỗi lượt user (để dựng playbook).

Mỗi lượt đã chọn: yêu cầu gốc, câu trả lời AI ngay trước (cắt gọn), lượt user. LLM trả loại phản hồi, khía cạnh,
mức riêng, đoạn trích nguyên văn. Đoạn trích không phải chuỗi con của lượt user thì hỏi lại một lần, vẫn sai thì loại.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Optional

from pc.mining.common import MOVE_DEF, MOVES
from pc.schema import Session, Turn
from pc.textutil import is_substring

from .common import NeedAgents, ask_many, base_dir, chunks, clip, role, settings, stable, work_dir, write_jsonl

TYPES = ("correct_with_fix", "reject_no_fix", "rephrase_retry", "constraint_add", "challenge", "redirect_method",
         "accept_explicit", "none")
TYPE_DEF = {
    "correct_with_fix": "says the answer is wrong or not good enough AND gives the right content or direction",
    "reject_no_fix": "says it is wrong or unsatisfying but not how to fix it",
    "rephrase_retry": "repeats the same request in other words",
    "constraint_add": "adds a requirement the answer missed (format, depth, scope, language...)",
    "challenge": "questions correctness, asks for evidence, asks to state assumptions",
    "redirect_method": "imposes their own way of working: where to start, which order or method",
    "accept_explicit": "praises or confirms the answer with specific content",
    "none": "no feedback on the answer (new question, follow-up, thanks, info)",
}
ASPECTS = {"correctness": "đúng sai", "reasoning_method": "cách lập luận", "evidence_rigor": "chuẩn bằng chứng",
           "assumptions": "giả định", "scope_depth": "độ sâu", "structure_format": "cấu trúc",
           "tone_style": "giọng văn", "actionability": "tính hành động", "domain_norm": "chuẩn ngành"}
LEVELS = ("universal", "domain_norm", "personal")
CORRECTIONS = TYPES[:6]


def _ctx(s: Session, turn_id: str) -> tuple[Optional[Turn], Optional[Turn], Optional[Turn], Turn]:
    """(lượt user đầu phiên, yêu cầu = lượt user trước, câu trả lời AI ngay trước, lượt user)."""
    path = s.active_turns
    k = next(i for i, t in enumerate(path) if t.turn_id == turn_id)
    users = [t for t in path[:k] if t.role == "user"]
    asst = next((t for t in reversed(path[:k]) if t.role == "assistant"), None)
    return (users[0] if users else None), (users[-1] if users else None), asst, path[k]


def item_text(i: int, s: Session, turn_id: str) -> str:
    first, req, asst, user = _ctx(s, turn_id)
    L = [f"[t{i}]"]
    if first is not None and req is not None and first.turn_id != req.turn_id:
        L.append(f"SESSION_START:\n{clip(first.text, 300)}")
    L.append(f"REQUEST (previous user turn):\n{clip(req.text, 500) if req else '(none)'}")
    L.append(f"AI_ANSWER:\n{clip(asst.text, 1200, 300) if asst else '(none)'}")
    L.append(f"USER_TURN:\n{clip(user.text, 1000)}")
    return "\n".join(L)


def mine_prompt(items: list[str], note: str = "") -> str:
    defs = "\n".join(f"  - {k}: {v}" for k, v in TYPE_DEF.items())
    p = (
        "Each item is one USER_TURN written right after an AI_ANSWER. Classify how the user reacts to that answer.\n\n"
        f"type (exactly one):\n{defs}\n"
        f"aspects (list, any of): {', '.join(ASPECTS)}. Empty when type is none.\n"
        "level: universal (anyone would correct this, e.g. code crashes, factual error) | domain_norm (a shared norm of "
        "the field) | personal (this user's own taste, standard or method). null when type is none.\n"
        "quote: an EXACT verbatim substring of USER_TURN that shows the reaction (copy characters exactly, no "
        "translation, no fixing typos). \"\" when type is none.\n"
        "want: one short Vietnamese sentence: what the user wants the AI to do (or keep doing), stated as a reusable "
        "standard, without names, numbers or project details. \"\" when type is none.\n"
        "issue: one short Vietnamese sentence: what in AI_ANSWER triggered the reaction. \"\" when type is none.\n"
        "reusable: true if the lesson would apply to other tasks of this kind, false if it only fits this one task.\n\n"
        "<data>\n" + "\n\n".join(items) + "\n</data>\n\n"
        "Return JSON exactly like: {\"items\": [{\"id\": \"t1\", \"type\": \"...\", \"aspects\": [], \"level\": null, "
        "\"quote\": \"\", \"want\": \"\", \"issue\": \"\", \"reusable\": false}, ...]} with one entry per item."
    )
    if note:
        p += f"\n\nNOTE: {note}"
    return p


def validate(d: dict, user_text: str) -> Optional[dict]:
    """Chuẩn hoá một mục. None nếu sai (loại không hợp lệ, thiếu mức, hoặc trích dẫn không phải chuỗi con)."""
    if not isinstance(d, dict) or d.get("type") not in TYPES:
        return None
    if d["type"] == "none":
        return {"type": "none"}
    if d.get("level") not in LEVELS:
        return None
    q = str(d.get("quote") or "").strip()
    if not q or not is_substring(q, user_text):
        return None
    return {"type": d["type"], "aspects": [a for a in d.get("aspects") or [] if a in ASPECTS], "level": d["level"],
            "quote": q, "want": str(d.get("want") or "")[:300], "issue": str(d.get("issue") or "")[:300],
            "reusable": bool(d.get("reusable"))}


RETRY_NOTE = ("Some items were invalid before: every non-none item needs a valid level and a quote copied "
              "character-for-character from its USER_TURN.")


def _ask(cfg, llm, groups: list[list[dict]], by_sid, note: str = ""):
    prompts = [mine_prompt([item_text(i + 1, by_sid[r["session_id"]], r["turn_id"]) for i, r in enumerate(g)], note)
               for g in groups]
    return ask_many(llm, role(cfg, "cheap"), prompts, tag="mine", workers=settings(cfg)["workers"],
                    check=lambda d: isinstance(d.get("items"), list), max_tokens=6000)


def _collect(groups, res, by_sid) -> tuple[dict[str, dict], list[dict]]:
    got, bad = {}, []
    for g, ans in zip(groups, res.answers):
        if ans is None:
            continue
        items = {str(x.get("id")): x for x in ans.get("items") or [] if isinstance(x, dict)}
        for i, r in enumerate(g):
            user = _ctx(by_sid[r["session_id"]], r["turn_id"])[3]
            v = validate(items.get(f"t{i + 1}"), user.text)
            if v is None:
                bad.append(r)
            else:
                got[r["turn_id"]] = v
    return got, bad


def event_id(turn_id: str) -> str:
    return "E" + hashlib.sha1(turn_id.encode()).hexdigest()[:8]


def run_mine(cfg, llm, sessions: list[Session], selected: list[dict]) -> list[dict]:
    """Nhãn từng lượt lưu ở `mine_labels.jsonl`: chạy lại (thêm lượt, export mới) chỉ khai thác lượt chưa có nhãn."""
    from .common import read_jsonl
    st = settings(cfg)
    by_sid = {s.session_id: s for s in sessions}
    store_p = base_dir(cfg) / "mine_labels.jsonl"  # dùng chung mọi capsule
    store = {r["turn_id"]: r["label"] for r in read_jsonl(store_p)}
    sel = sorted(selected, key=lambda r: (r["domain"], r["session_id"], r["turn_id"]))
    todo = [r for r in sel if r["turn_id"] not in store]
    groups = chunks(todo, st["batch_mine"])
    res = _ask(cfg, llm, groups, by_sid)
    got, bad = _collect(groups, res, by_sid)
    pending = res.pending
    bad2: list[dict] = []
    if bad and not res.pending:
        res2 = _ask(cfg, llm, chunks(bad, st["batch_mine"]), by_sid, RETRY_NOTE)
        got2, bad2 = _collect(chunks(bad, st["batch_mine"]), res2, by_sid)
        got.update(got2)
        pending += res2.pending
    if pending:
        raise NeedAgents("Bước 4 (khai thác)", pending)
    for r in todo:  # lượt sai hai lần: nhãn None (đã loại), không hỏi lại
        store[r["turn_id"]] = got.get(r["turn_id"])
    write_jsonl(store_p, [{"turn_id": k, "label": v} for k, v in store.items()])
    got = {r["turn_id"]: store[r["turn_id"]] for r in sel}
    dropped = sum(1 for r in sel if store[r["turn_id"]] is None)
    events = []
    for r in sel:
        v = got.get(r["turn_id"])
        if not v or v["type"] == "none":
            continue
        events.append({"event_id": event_id(r["turn_id"]), "turn_id": r["turn_id"], "session_id": r["session_id"],
                       "domain": r["domain"], "task_type": r["task_type"], "created_at": r.get("created_at"),
                       **v, "why": r.get("why"), "score": r.get("score")})
    write_jsonl(work_dir(cfg) / "events.jsonl", events)
    stats = {"selected": len(sel), "labeled": len(sel) - dropped, "dropped_invalid": dropped, "events": len(events),
             "new_this_run": len(todo),
             "errors": res.errors[:5]}
    from .common import write_json
    write_json(work_dir(cfg) / "mine_stats.json", stats)
    return events


# ---------- move cho playbook ----------

def move_sessions(sessions: list[Session], labels: dict[str, dict], chosen: list[str], min_sessions: int,
                  per_group: int, min_user_turns: int = 3) -> list[Session]:
    groups: dict[tuple, list[Session]] = defaultdict(list)
    for s in sessions:
        lab = labels.get(s.session_id)
        if lab and lab["domain"] in chosen and s.n_user_turns >= min_user_turns:
            groups[(lab["domain"], lab["task_type"])].append(s)
    out = []
    for g in groups.values():
        if len(g) < min_sessions:
            continue
        g.sort(key=lambda s: (-s.n_user_turns, stable("mv", s.session_id)))
        out += g[:per_group]
    return sorted(out, key=lambda s: s.session_id)


MAX_TURNS = 25


def moves_prompt(batch: list[Session]) -> str:
    defs = "; ".join(f"{k} ({v})" for k, v in MOVE_DEF.items())
    parts = []
    for i, s in enumerate(batch):
        users = [t for t in s.active_turns if t.role == "user"][:MAX_TURNS]
        lines = "\n".join(f"  u{j + 1}: {clip(' '.join(t.text.split()), 160)}" for j, t in enumerate(users))
        parts.append(f"[s{i + 1}] TITLE: {s.title or '(none)'} ({len(users)} user turns)\n{lines}")
    return (
        "For each session, give the MOVE of every user turn, in order. A move is what the user is doing in the "
        f"conversation. Choose from: {defs}.\n\n<data>\n" + "\n\n".join(parts) + "\n</data>\n\n"
        "Return JSON exactly like: {\"sessions\": [{\"id\": \"s1\", \"moves\": [\"frame\", \"delegate\", ...]}, ...]} "
        "with exactly one move per user turn."
    )


def run_moves(cfg, llm, sessions: list[Session], labels: dict[str, dict], chosen: list[str]) -> list[dict]:
    st = settings(cfg)
    ms = move_sessions(sessions, labels, chosen, st["playbook_min_sessions"], st["moves_per_group"])
    batches = chunks(ms, st["batch_moves"])
    res = ask_many(llm, role(cfg, "cheap"), [moves_prompt(b) for b in batches], tag="moves",
                   workers=st["workers"], check=lambda d: isinstance(d.get("sessions"), list))
    if res.pending:
        raise NeedAgents("Bước 4 (gán move)", res.pending)
    rows = []
    for b, ans in zip(batches, res.answers):
        got = {str(x.get("id")): x for x in (ans or {}).get("sessions") or [] if isinstance(x, dict)}
        for i, s in enumerate(b):
            mv = (got.get(f"s{i + 1}") or {}).get("moves") or []
            n = min(s.n_user_turns, MAX_TURNS)
            if len(mv) != n or any(m not in MOVES for m in mv):
                continue
            lab = labels[s.session_id]
            rows.append({"session_id": s.session_id, "domain": lab["domain"], "task_type": lab["task_type"],
                         "created_at": s.created_at, "n_user_turns": s.n_user_turns, "moves": mv})
    write_jsonl(work_dir(cfg) / "moves.jsonl", rows)
    return rows
