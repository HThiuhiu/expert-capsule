"""Gom "source material" cho distilly analyzer từ dữ liệu đã mining (thay cho bước import tài liệu của distilly).

Mỗi domain một tài liệu bằng chứng: rubric đã quy nạp, lời chê thật, quy trình làm việc (chuỗi move, Driver L2),
cách diễn đạt (đặc trưng bề mặt L1), lời khen, thói quen xuyên phiên (L3). Mọi trích dẫn đều ngắn.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from ..mining.common import clip
from ..mining.gold import read_jsonl
from ..schema import Session

_GREET = re.compile(r"^\s*(chào|hi|hello|hey|xin chào|alo)\b", re.I)
_THANK = re.compile(r"(cảm ơn|cám ơn|thanks|thank you|tks)", re.I)
_NUM = re.compile(r"^\s*(\d+[.)]|[-*•])\s", re.M)


def surface(text: str) -> dict:
    """Driver L1: đặc trưng bề mặt của một lượt user."""
    t = text.strip()
    return {"tokens": len(t.split()), "greet": bool(_GREET.search(t)), "thanks": bool(_THANK.search(t)),
            "question": t.endswith("?") or "?" in t[-40:], "numbered": len(_NUM.findall(t)) >= 2,
            "paste": len(t) > 1500 or "```" in t}


def l1_stats(turns: list[str]) -> dict:
    fs = [surface(t) for t in turns]
    n = len(fs) or 1
    return {"n_turns": len(fs), "median_tokens": statistics.median([f["tokens"] for f in fs]) if fs else 0,
            **{k: round(sum(f[k] for f in fs) / n, 3) for k in ("greet", "thanks", "question", "numbered", "paste")}}


def _short(t: str, n: int) -> str:
    return clip(re.sub(r"\s+", " ", t).strip(), n)


def domain_index(cfg) -> tuple[dict, dict[str, list[str]]]:
    meta = {m["session_id"]: m for m in read_jsonl(cfg.path("interim") / "session_labels.jsonl")}
    by = defaultdict(list)
    for sid, m in meta.items():
        by[m.get("domain") or "other"].append(sid)
    return meta, by


def build(cfg, domain: str, sids: set[str], sessions: dict[str, Session], rules: list[dict], cases: dict,
          events: list[dict], turn_rows: dict[str, dict], meta: dict, max_chars: int = 60000) -> tuple[str, dict]:
    ev = [e for e in events if e["session_id"] in sids]
    rl = [r for r in rules if r["status"] != "superseded" and set(r["sessions"]) & sids]
    rl.sort(key=lambda r: (r["status"] != "supported", -len(r["support_events"]), r["rule_id"]))
    tts = Counter(meta[s].get("task_type") for s in sids if s in meta)
    L = [f"# Source material: domain `{domain}`", "",
         f"Nguồn: lịch sử chat của người dùng với AI (ChatGPT + Claude). {len(sids)} phiên, {len(ev)} lượt sửa sai.",
         "task_type: " + ", ".join(f"{k} {v}" for k, v in tts.most_common()), "",
         "Tiêu đề phiên tiêu biểu: " + "; ".join(_short(sessions[s].title, 60) for s in sorted(sids)[:40]
                                                 if s in sessions and sessions[s].title), ""]
    L += ["## 1. Rubric đã quy nạp (người dùng muốn AI làm gì, khi nào)", ""]
    for r in rl[:60]:
        L.append(f"- [{r['status']}, {len(r['support_events'])} event/{r['n_sessions']} phiên, {r['idiosyncrasy']}] "
                 f"Khi {r['when']} → {r['do_or_dont']} Vì: {r.get('because') or '?'}")
    L += ["", "## 2. Lời chê thật (nguyên văn, đã cắt)", ""]
    for e in sorted(ev, key=lambda e: (e['feedback'].get('idiosyncrasy') != 'personal', e['event_id']))[:40]:
        c = cases.get(e["event_id"], {})
        L.append(f"- ({e['feedback']['primary_label']}; {e['task'].get('task_type')}) user: \"{_short(e['feedback_text'], 220)}\""
                 + (f" | AI bị chê vì: {c['cue']}" if c.get("cue") else ""))
    # Driver L2: quy trình
    L += ["", "## 3. Quy trình làm việc (chuỗi move của user trong phiên)", ""]
    seqs, trans, opens, closes = [], Counter(), [], []
    for s in sorted(sids):
        if s not in sessions:
            continue
        us = [t for t in sessions[s].active_turns if t.role == "user"]
        mv = [(turn_rows.get(t.turn_id, {}).get("labeler") or {}).get("move") for t in us]
        mv = [m for m in mv if m]
        if len(mv) >= 3:
            seqs.append((meta.get(s, {}).get("task_type"), mv))
        trans.update(zip(mv, mv[1:]))
        if us:
            opens.append(_short(us[0].text, 180))
            if len(us) > 2:
                closes.append(_short(us[-1].text, 140))
    for tt, mv in seqs[:25]:
        L.append(f"- {tt}: " + " → ".join(mv[:14]))
    L += ["", "Chuyển tiếp hay gặp: " + ", ".join(f"{a}→{b} ({n})" for (a, b), n in trans.most_common(12)), "",
          "Cách mở phiên (lượt user đầu):"] + [f"- \"{o}\"" for o in opens[:15]]
    L += ["", "Cách kết phiên (lượt user cuối):"] + [f"- \"{c}\"" for c in closes[:10]]
    # L1 + lời khen
    users = [t.text for s in sids if s in sessions for t in sessions[s].active_turns if t.role == "user"]
    st = l1_stats(users)
    L += ["", "## 4. Cách diễn đạt khi làm việc với AI (thống kê bề mặt)", "",
          f"- Số lượt: {st['n_turns']}, trung vị {st['median_tokens']} từ/lượt.",
          f"- Tỉ lệ: chào {st['greet']:.0%}, cảm ơn {st['thanks']:.0%}, câu hỏi {st['question']:.0%}, "
          f"đánh số yêu cầu {st['numbered']:.0%}, dán dữ liệu/code dài {st['paste']:.0%}.", "",
          "Ví dụ lượt ngắn (nguyên văn):"]
    shorts = [u for u in users if 3 <= len(u.split()) <= 30]
    L += [f"- \"{_short(u, 160)}\"" for u in shorts[:: max(1, len(shorts) // 30)][:30]]
    praise = [turn_rows[t]["_text"] for t in turn_rows if turn_rows[t].get("_text") and turn_rows[t]["session_id"] in sids
              and (turn_rows[t].get("labeler") or {}).get("primary_label") == "accept_explicit"]
    L += ["", "## 5. Khi người dùng hài lòng (accept_explicit)", ""] + [f"- \"{_short(p, 160)}\"" for p in praise[:15]]
    txt = "\n".join(L)
    return txt[:max_chars], {"n_sessions": len(sids), "n_events": len(ev), "n_rules": len(rl),
                              "n_supported": sum(r["status"] == "supported" for r in rl), "l1": st,
                              "task_types": dict(tts)}
