"""Thử nhanh capsule trước Module 2 (không thay cho eval chính thức C).

Item: correction event ở split dev, cộng event train chấm theo kiểu bỏ-một-phiên (capsule bỏ mọi quy tắc có bằng chứng
từ phiên của item). Không đụng split test.

A. Đoán lời chê: thấy yêu cầu + câu trả lời bị bác, liệt kê 3 điều người dùng sẽ chê. Judge so với lời chê thật.
B. Sinh câu trả lời: thấy yêu cầu, viết câu trả lời. Judge so cặp generic vs capsule (đảo vị trí 2 lần).

Lệch C5: judge cùng họ với generator (chỉ có DeepSeek).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import load_config
from ..induce.render import _line
from ..llm import LLM
from ..mining.common import clip, parse_json
from ..mining.gold import read_jsonl

GENERIC = "You are a helpful assistant."
CAP_HEAD = ("Bạn là trợ lý cho một người dùng cụ thể. Dưới đây là rubric học từ các lần người này sửa AI. "
            "Áp dụng quy tắc có `Khi` khớp ngữ cảnh; bỏ qua quy tắc không khớp.\n\n")


def self_prompt(root: Path) -> str:
    t = (root / "eval" / "baselines" / "self_prompt.md").read_text(encoding="utf-8")
    return t.split("\n---\n", 1)[-1].strip()


def capsule_prompt(rules: list[dict], drop_session: str) -> str:
    keep = [r for r in rules if r["status"] != "superseded" and r["exclusive"] and drop_session not in r["sessions"]]
    return CAP_HEAD + "\n".join(_line(r) for r in keep)


def items(cfg) -> list[dict]:
    sp = json.loads((cfg.path("interim") / "splits.json").read_text(encoding="utf-8"))["sessions"]
    out = []
    for e in read_jsonl(cfg.path("interim") / "events.jsonl"):
        s = sp.get(e["session_id"])
        if s in ("dev", "train") and (e.get("feedback_text") or "").strip() and (e.get("rejected_text") or "").strip():
            out.append({**e, "split": s})
    return out


def _req(e):
    return clip(e["task"].get("request_text") or "", 4000, 1000)


# ---------- A ----------

def critique_msgs(system: str, e: dict) -> list[dict]:
    u = ("Dưới đây là yêu cầu của người dùng và câu trả lời của AI. Đoán 3 điều người dùng này sẽ chê hoặc yêu cầu "
         "sửa ở câu trả lời, xếp từ khả năng cao nhất. Mỗi ý một câu, cụ thể.\n\n"
         f"<request>\n{_req(e)}\n</request>\n\n<answer>\n{clip(e['rejected_text'], 5000, 1500)}\n</answer>\n\n"
         'Trả về JSON: {"critiques": ["...", "...", "..."]}')
    return [{"role": "system", "content": system}, {"role": "user", "content": u}]


def judge_a_msgs(e: dict, crit: list[str]) -> list[dict]:
    u = ("REAL user feedback on an AI answer, and PREDICTED complaints. Does any predicted complaint capture the same "
         "main point as the real feedback? same = same point; partial = related but misses the key point; "
         "different = none.\n\n"
         f"<real>\n{clip(e['feedback_text'], 2000, 500)}\n</real>\n\n<predicted>\n"
         + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(crit)) + "\n</predicted>\n\n"
         'Return JSON: {"best": <1-3 or 0>, "match": "same|partial|different"}')
    return [{"role": "system", "content": "You are a strict evaluator. Reply with one JSON object."},
            {"role": "user", "content": u}]


# ---------- B ----------

def answer_msgs(system: str, e: dict) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": _req(e)}]


def judge_b_msgs(e: dict, x: str, y: str) -> list[dict]:
    u = ("A user made a REQUEST. Later they gave FEEDBACK on a first answer, which shows what this user wants. "
         "Which of the two new answers better satisfies what this user wants (including the feedback), "
         "while still answering the request? Ignore length unless the feedback is about length.\n\n"
         f"<request>\n{clip(_req(e), 3000, 500)}\n</request>\n\n<feedback>\n{clip(e['feedback_text'], 2000, 500)}\n"
         f"</feedback>\n\n<answer_X>\n{clip(x, 4000, 1000)}\n</answer_X>\n\n<answer_Y>\n{clip(y, 4000, 1000)}\n</answer_Y>\n\n"
         'Return JSON: {"winner": "X|Y|tie", "why": "<one short sentence>"}')
    return [{"role": "system", "content": "You are a strict evaluator. Reply with one JSON object."},
            {"role": "user", "content": u}]


SCORE = {"same": 1.0, "partial": 0.5, "different": 0.0}


def boot_ci(diffs: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not diffs:
        return 0.0, 0.0
    rng = random.Random(seed)
    m = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return m[int(.025 * n)], m[int(.975 * n)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--b-limit", type=int, default=60, help="số item cho bài B (dev trước, rồi train)")
    ap.add_argument("--model", default="deepseek/deepseek-v4.1-flash", help="generator và judge cho pilot")
    ap.add_argument("--limit", type=int, help="chỉ chạy N item đầu (dev trước)")
    a = ap.parse_args(argv)
    cfg = load_config()
    llm = LLM(cfg.path("cache"))
    gen = judge = {"model": a.model, "temperature": 0}
    cfg.raw["models"]["generator"] = cfg.raw["models"]["judge"] = gen
    rules = read_jsonl(cfg.path("capsule") / "rules.jsonl")
    sp_text = self_prompt(cfg.root)
    its = sorted(items(cfg), key=lambda e: (e["split"] != "dev", e["event_id"]))[:a.limit]
    systems = {"generic": lambda e: GENERIC, "self_prompt": lambda e: sp_text,
               "capsule": lambda e: capsule_prompt(rules, e["session_id"])}

    def run_a(e):
        out = {}
        for name, sysf in systems.items():
            d = parse_json(llm.complete(gen, critique_msgs(sysf(e), e), max_tokens=3000)) or {}
            crit = [str(c) for c in (d.get("critiques") or [])][:3] or ["(không có)"]
            j = parse_json(llm.complete(judge, judge_a_msgs(e, crit), max_tokens=2000)) or {}
            out[name] = {"critiques": crit, "match": j.get("match") if j.get("match") in SCORE else "different"}
        return e["event_id"], out

    def run_b(e):
        ans = {n: llm.complete(gen, answer_msgs(systems[n](e), e), max_tokens=4000) for n in ("generic", "capsule")}
        votes = []
        for x, y in (("generic", "capsule"), ("capsule", "generic")):
            j = parse_json(llm.complete(judge, judge_b_msgs(e, ans[x], ans[y]), max_tokens=2000)) or {}
            w = {"X": x, "Y": y}.get(j.get("winner"), "tie")
            votes.append((w, j.get("why", "")))
        w = votes[0][0] if votes[0][0] == votes[1][0] else "tie"
        return e["event_id"], {"winner": w, "votes": votes, "answers": ans}

    with ThreadPoolExecutor(a.workers) as ex:
        A = dict(ex.map(run_a, its))
    b_items = sorted(its, key=lambda e: (e["split"] != "dev", e["event_id"]))[:a.b_limit]
    with ThreadPoolExecutor(a.workers) as ex:
        B = dict(ex.map(run_b, b_items))

    out = cfg.root / "eval" / "runs" / "pilot"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.jsonl", "w", encoding="utf-8") as f:
        for e in its:
            f.write(json.dumps({"event_id": e["event_id"], "split": e["split"], "A": A[e["event_id"]],
                                "B": B.get(e["event_id"])}, ensure_ascii=False) + "\n")
    rep = report(its, A, B, b_items, cfg, llm, rules)
    (cfg.path("reports") / "step2_pilot_eval.md").write_text(rep, encoding="utf-8")
    print(rep)
    return 0


def report(its, A, B, b_items, cfg, llm, rules) -> str:
    L = ["# Thử nhanh: có chưng cất vs không (pilot, trước Module 2)", "",
         f"Generator và judge: `{cfg.model('generator')['model']}` / `{cfg.model('judge')['model']}`. "
         f"Chi phí API lần chạy: ~${llm.usage.cost(cfg.raw.get('pricing', {})):.3f}.", "",
         "Item: event ở dev, cộng event train chấm kiểu bỏ-một-phiên (capsule bỏ quy tắc có bằng chứng từ phiên đó). "
         "Không đụng test. Judge cùng họ với generator nên kết quả chỉ để tham khảo.", "",
         "## A. Đoán lời chê (điểm: same=1, partial=0,5)", "",
         "| Nhóm | n | generic | self_prompt | capsule | capsule − generic (KTC 95%) |", "|---|---|---|---|---|---|"]
    groups = defaultdict(list)
    for e in its:
        groups["tất cả"].append(e)
        groups[e["split"]].append(e)
        groups["idiosyncrasy=" + str(e["feedback"].get("idiosyncrasy"))].append(e)
        groups["generalizability=" + str(e["feedback"].get("generalizability"))].append(e)
    for g, es in groups.items():
        sc = {n: [SCORE[A[e["event_id"]][n]["match"]] for e in es] for n in ("generic", "self_prompt", "capsule")}
        d = [c - g0 for c, g0 in zip(sc["capsule"], sc["generic"])]
        lo, hi = boot_ci(d)
        L.append(f"| {g} | {len(es)} | " + " | ".join(f"{sum(v) / len(v):.2f}" for v in sc.values())
                 + f" | {sum(d) / len(d):+.2f} ({lo:+.2f}, {hi:+.2f}) |")
    L += ["", "## B. Sinh câu trả lời: capsule vs generic (judge so cặp, đảo vị trí)", ""]
    wins = defaultdict(lambda: defaultdict(int))
    for e in b_items:
        for g in ("tất cả", e["split"]):
            wins[g][B[e["event_id"]]["winner"]] += 1
    L += ["| Nhóm | n | capsule thắng | generic thắng | hoà/không nhất quán |", "|---|---|---|---|---|"]
    for g, w in wins.items():
        n = sum(w.values())
        L.append(f"| {g} | {n} | {w['capsule']} | {w['generic']} | {w['tie']} |")
    L += ["", "## Ví dụ (5 item dev, bài A)", ""]
    for e in [x for x in its if x["split"] == "dev"][:5]:
        r = A[e["event_id"]]
        L += [f"### `{e['event_id']}`", "", f"- Lời chê thật: {clip(e['feedback_text'], 300).strip()}"]
        for n in ("generic", "capsule"):
            L.append(f"- {n} ({r[n]['match']}): " + " / ".join(c[:160] for c in r[n]["critiques"]))
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
