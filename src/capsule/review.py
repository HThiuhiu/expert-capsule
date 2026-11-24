"""Bước 7: duyệt (CLI). Hiện từng luật kèm 2 đoạn trích bằng chứng từ 2 phiên. Chọn: giữ, sửa câu chữ, sửa phạm vi,
xoá. Luật bị xoá không được học lại từ cùng bằng chứng (Bước 5 bỏ luật trùng >= 50% event với luật đã xoá).
Các cặp mâu thuẫn được hỏi trực tiếp; câu trả lời được đưa vào lần tổng hợp sau.

Quyết định lưu ở `data/lite/review.json`, gắn với mã luật và tập event; luật đổi bằng chứng quá nhiều (Jaccard < 0,5)
thì coi như luật mới, cần duyệt lại.
"""
from __future__ import annotations

import copy
import datetime as dt
from typing import Callable, Optional

from .common import read_json, read_jsonl, work_dir, write_json


def load(cfg) -> dict:
    rv = read_json(work_dir(cfg) / "review.json", {}) or {}
    return {"decisions": rv.get("decisions", {}), "deleted": rv.get("deleted", []), "answers": rv.get("answers", [])}


def save(cfg, rv: dict) -> None:
    write_json(work_dir(cfg) / "review.json", rv)


def _jac(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def decision_for(rv: dict, rule: dict) -> Optional[dict]:
    d = rv["decisions"].get(rule["code"])
    if d and _jac(d.get("events", []), rule["events"]) >= 0.5:
        return d
    return None


EDITABLE = ("when", "do", "because", "scope", "exceptions")


def apply(synth: dict, rv: dict) -> dict:
    """Bản sao synth đã áp quyết định duyệt. Luật xoá bị bỏ; luật sửa thay câu chữ; đánh dấu `reviewed`."""
    s = copy.deepcopy(synth)

    def fix(rules: list[dict]) -> list[dict]:
        out = []
        for r in rules:
            d = decision_for(rv, r)
            if d and d["action"] == "delete":
                continue
            if d:
                for f in EDITABLE:
                    if d.get(f):
                        r[f] = d[f]
            r["reviewed"] = bool(d)
            out.append(r)
        return out

    s["core"] = fix(s.get("core", []))
    for x in s.get("domains", {}).values():
        x["rules"] = fix(x["rules"])
    return s


def all_rules(synth: dict) -> list[tuple[str, dict]]:
    out = [("lõi chung", r) for r in synth.get("core", [])]
    for x in synth.get("domains", {}).values():
        out += [(x["name"], r) for r in x["rules"]]
    return out


def evidence(rule: dict, evs: dict[str, dict], k: int = 2) -> list[dict]:
    """k đoạn trích từ k phiên khác nhau (ưu tiên personal)."""
    seen, out = set(), []
    for eid in sorted(rule["events"], key=lambda x: (evs.get(x, {}).get("level") != "personal", x)):
        e = evs.get(eid)
        if e and e["session_id"] not in seen:
            seen.add(e["session_id"])
            out.append(e)
        if len(out) >= k:
            break
    return out


def rule_text(r: dict) -> str:
    from .package.skill import rule_line
    return rule_line(r)


def listing(cfg) -> str:
    synth = read_json(work_dir(cfg) / "synth.json")
    if not synth:
        return "Chưa có luật. Chạy `capsule build` trước."
    rv = load(cfg)
    L = ["| Mã | Lĩnh vực | Event | Duyệt | Luật |", "|---|---|---|---|---|"]
    for where, r in all_rules(synth):
        d = decision_for(rv, r)
        L.append(f"| {r['code']} | {where} | {len(r['events'])} | {d['action'] if d else 'chưa'} | {rule_text(r)[:120]} |")
    n_conf = sum(len(x["conflicts"]) for x in synth["domains"].values())
    L.append(f"\nMâu thuẫn chờ trả lời: {n_conf - len(rv['answers'])} / {n_conf}.")
    return "\n".join(L)


MENU = "[g]iữ  [s]ửa câu chữ  [p]hạm vi  [x]oá  [b]ỏ qua  [q] thoát"


def interactive(cfg, only_pending: bool = True, ask: Callable[[str], str] = input, say=print) -> int:
    synth = read_json(work_dir(cfg) / "synth.json")
    if not synth:
        say("Chưa có luật. Chạy `capsule build` trước.")
        return 2
    evs = {e["event_id"]: e for e in read_jsonl(work_dir(cfg) / "events.jsonl")}
    rv = load(cfg)
    now = dt.datetime.now().isoformat(timespec="seconds")
    quit_ = False
    try:
        for where, r in all_rules(synth):
            if only_pending and decision_for(rv, r):
                continue
            say(f"\n{r['code']} ({where}, {len(r['events'])} event, {len(r['sessions'])} phiên, {r['level']})")
            say("  " + rule_text(r))
            if r.get("scope"):
                say(f"  Phạm vi: {r['scope']}")
            for e in evidence(r, evs):
                say(f"  - \"{e['quote'][:200]}\"  ({(e.get('created_at') or '')[:10]})")
            c = ask(MENU + " > ").strip().lower()[:1]
            if c == "q":
                quit_ = True
                break
            if c not in "gspx" or not c:
                continue
            d = {"action": {"g": "keep", "s": "edit", "p": "scope", "x": "delete"}[c], "events": r["events"], "at": now}
            if c == "s":
                d["when"] = ask(f"  Khi [{r['when']}]: ").strip() or r["when"]
                d["do"] = ask(f"  Làm [{r['do']}]: ").strip() or r["do"]
                d["because"] = ask(f"  Vì [{r['because']}]: ").strip() or r["because"]
            if c == "p":
                d["scope"] = ask(f"  Phạm vi [{r.get('scope', '')}]: ").strip() or r.get("scope", "")
                d["exceptions"] = ask(f"  Ngoại lệ [{r.get('exceptions', '')}]: ").strip() or r.get("exceptions", "")
            rv["decisions"][r["code"]] = d
            if c == "x":
                rv["deleted"].append({"code": r["code"], "events": r["events"], "at": now})
            save(cfg, rv)
        asked = {a["question"] for a in rv["answers"]}
        for slug, x in ([] if quit_ else synth["domains"].items()):
            for cf in x["conflicts"]:
                if cf["question"] in asked:
                    continue
                say(f"\nMâu thuẫn ({x['name']}): {cf['question']}")
                a = ask("  Trả lời (Enter để bỏ qua) > ").strip()
                if a:
                    rv["answers"].append({"domain": slug, "question": cf["question"], "answer": a, "at": now})
                    save(cfg, rv)
    except EOFError:
        pass
    save(cfg, rv)
    say("\nĐã lưu. Có quyết định mới: chạy `capsule package`. Có trả lời mâu thuẫn hoặc xoá luật: chạy lại "
        "`capsule build` để tổng hợp lại.")
    return 0
