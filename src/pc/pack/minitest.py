"""Thử nhỏ (5-10 item): bộ chuyên gia vs không chưng cất, trên event split test (chưa dùng để dựng bộ).

Generator viết câu trả lời cho yêu cầu gốc, một lần không có persona, một lần với SKILL.md của bộ đúng domain.
Judge (khác họ) xem lời chê thật của người dùng rồi chọn bản hợp ý hơn, chấm 2 lần đảo vị trí.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..eval.pilot import GENERIC, answer_msgs, judge_b_msgs
from ..llm import LLM
from ..mining.common import clip, parse_json, stable_frac
from ..mining.gold import read_jsonl


def run(cfg, packs: dict[str, Path], n: int = 8, log=print) -> str:
    inter = cfg.path("interim")
    sp = json.loads((inter / "splits.json").read_text(encoding="utf-8"))["sessions"]
    meta = {m["session_id"]: m for m in read_jsonl(inter / "session_labels.jsonl")}
    evs = [e for e in read_jsonl(inter / "events.jsonl") if sp.get(e["session_id"]) == "test"
           and (e.get("feedback_text") or "").strip() and e["feedback"].get("primary_label") != "rephrase_retry"]
    evs.sort(key=lambda e: stable_frac("minitest", e["event_id"]))
    picked, seen = [], set()
    for e in evs:  # mỗi phiên tối đa 1 item, ưu tiên personal
        if e["session_id"] in seen:
            continue
        seen.add(e["session_id"])
        picked.append(e)
    picked.sort(key=lambda e: e["feedback"].get("idiosyncrasy") != "personal")
    picked = picked[:n]
    llm = LLM(cfg.path("cache"))
    gen, judge = cfg.model("generator"), cfg.model("judge")
    rows = []
    for e in picked:
        dom = meta.get(e["session_id"], {}).get("domain")
        p = packs.get(dom) or packs.get("all")
        skill = (p / "SKILL.md").read_text(encoding="utf-8")
        ans = {"generic": llm.complete(gen, answer_msgs(GENERIC, e), max_tokens=4000),
               "pack": llm.complete(gen, answer_msgs(skill, e), max_tokens=4000)}
        votes = []
        for x, y in (("generic", "pack"), ("pack", "generic")):
            j = parse_json(llm.complete(judge, judge_b_msgs(e, ans[x], ans[y]), max_tokens=1500)) or {}
            votes.append(({"X": x, "Y": y}.get(j.get("winner"), "tie"), j.get("why", "")))
        w = votes[0][0] if votes[0][0] == votes[1][0] else "tie"
        rows.append({"e": e, "pack": p.name, "ans": ans, "votes": votes, "winner": w})
        log(f"{e['event_id'][:20]} [{p.name}] -> {w}")
    win = sum(r["winner"] == "pack" for r in rows)
    lose = sum(r["winner"] == "generic" for r in rows)
    L = ["# Thử nhỏ: bộ chuyên gia vs không chưng cất", "",
         f"{len(rows)} item từ split test (không dùng để dựng bộ). Generator `{gen['model']}`, judge `{judge['model']}` "
         f"(khác họ). Mỗi cặp chấm 2 lần đảo vị trí; 2 lần khác nhau thì tính hoà.", "",
         f"**Bộ chuyên gia thắng {win}, không chưng cất thắng {lose}, hoà {len(rows) - win - lose}.**", "",
         f"Chi phí API: ~${llm.usage.cost(cfg.raw.get('pricing', {})):.3f}.", "",
         "| # | Bộ dùng | Loại lời chê | Lời chê thật | Kết quả | Lý do judge |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        e = r["e"]
        L.append(f"| {i} | {r['pack']} | {e['feedback']['primary_label']}, {e['feedback'].get('idiosyncrasy')} | "
                 f"{clip(e['feedback_text'], 120).replace('|', '/').replace(chr(10), ' ')} | {r['winner']} | "
                 f"{(r['votes'][0][1] or '')[:140].replace('|', '/')} |")
    L += ["", "## Chi tiết", ""]
    for i, r in enumerate(rows, 1):
        e = r["e"]
        L += [f"### {i}. {r['winner']}", "", f"- Yêu cầu: {clip(e['task'].get('request_text') or '', 300)}",
              f"- Lời chê thật: {clip(e['feedback_text'], 300)}",
              f"- Không chưng cất: {clip(r['ans']['generic'], 500)}", f"- Bộ chuyên gia: {clip(r['ans']['pack'], 500)}", ""]
    return "\n".join(L).replace("\r", "")
