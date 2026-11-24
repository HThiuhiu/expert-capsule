"""Bước 5: tổng hợp luật (LLM mạnh, vài lệnh mỗi lĩnh vực).

Đợt A (độc lập nhau): mỗi lĩnh vực một lệnh cho luật + mâu thuẫn + tình huống; mỗi lĩnh vực một lệnh playbook (nếu có
task_type đủ 6 phiên); một lệnh sổ tay văn phong.
Đợt B (cần luật của đợt A): một lệnh gom lõi chung (luật có ở từ 2 lĩnh vực), mỗi lĩnh vực một lệnh câu trả lời mẫu.

Kiểm tra bằng code: luật dưới 2 event hoặc chỉ từ 1 phiên thành "ứng viên", không vào capsule. Event universal không
tạo luật. Luật trùng bằng chứng với luật người dùng đã xoá (Bước 7) thì bỏ.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from pc.mining.common import MOVE_DEF
from pc.textutil import detect_lang, is_substring, norm_ws

from .common import NeedAgents, ask_many, clip, read_json, role, settings, stable, work_dir, write_json
from .mine import ASPECTS

TYPE_VI = {"correct_with_fix": "sửa kèm cách đúng", "reject_no_fix": "bác, không nói cách sửa",
           "rephrase_retry": "hỏi lại bằng lời khác", "constraint_add": "thêm yêu cầu bị bỏ sót",
           "challenge": "hỏi vặn, đòi bằng chứng", "redirect_method": "áp cách làm riêng",
           "accept_explicit": "khen cụ thể"}


def event_line(e: dict) -> str:
    asp = ",".join(ASPECTS.get(a, a) for a in e.get("aspects") or [])
    once = " | một lần" if not e.get("reusable") else ""
    return (f"{e['event_id']} | {TYPE_VI.get(e['type'], e['type'])} | {asp or '-'} | {e['level']}{once} | "
            f"trích: \"{clip(norm_ws(e['quote']), 220)}\" | muốn: {e.get('want') or '-'} | AI đã: {e.get('issue') or '-'}")


def rules_prompt(name: str, events: list[dict], answers: list[dict]) -> str:
    owner = ""
    if answers:
        owner = ("\nOWNER DECISIONS on earlier contradictions (follow them):\n"
                 + "\n".join(f"- {a['question']} -> {a['answer']}" for a in answers) + "\n")
    return (
        f"Below are feedback events from one person's chats with AI in the field \"{name}\". Each line: event id | "
        "type | aspects | level | quote (verbatim) | what they want | what the AI did.\n\n"
        "Task, all text in Vietnamese:\n"
        "1. rules: write the standards this person enforces on AI answers in this field. Group events that express the "
        "same standard into ONE rule and list ALL their event ids. Each rule: when (the situation, concrete, without "
        "the word \"Khi\"), do (a concrete, checkable instruction to the AI, imperative; no vague adjectives like "
        "\"rõ ràng\", \"chất lượng\"), because (the reason; if the person never stated it, end with \"(suy luận)\"), "
        "scope (where it applies), exceptions (\"\" if none), level (personal or domain_norm). Do not invent "
        "standards that no event supports. Skip events marked \"một lần\" unless several events agree. At most 30 rules.\n"
        "2. conflicts: pairs of event groups where the person demanded opposite things. For each, a question for the "
        "person, like: \"Trong lĩnh vực X bạn từng đòi A và cũng từng đòi ngược lại. Khi nào thì A?\"\n"
        "3. cases: pick 3 to 8 most representative events and rewrite each as a short generic case (no names, numbers, "
        "file or project names): context, cue (what made the person react), judgment, action (what the AI should "
        "have done), exception, outcome.\n"
        + owner +
        "\n<data>\n" + "\n".join(event_line(e) for e in events) + "\n</data>\n\n"
        "Return JSON exactly like: {\"rules\": [{\"when\": \"...\", \"do\": \"...\", \"because\": \"...\", "
        "\"scope\": \"...\", \"exceptions\": \"\", \"level\": \"personal\", \"events\": [\"E...\"]}], "
        "\"conflicts\": [{\"events_a\": [\"E...\"], \"events_b\": [\"E...\"], \"question\": \"...\"}], "
        "\"cases\": [{\"event\": \"E...\", \"context\": \"...\", \"cue\": \"...\", \"judgment\": \"...\", "
        "\"action\": \"...\", \"exception\": \"\", \"outcome\": \"...\"}]}"
    )


def _rules_ok(d: dict) -> bool:
    return isinstance(d.get("rules"), list)


def check_rules(raw: list[dict], evs: dict[str, dict], blocked: list[set[str]]) -> list[dict]:
    """Kiểm tra bằng code: event hợp lệ, đếm phiên, hạ ứng viên, bỏ luật dựa trên bằng chứng của luật đã xoá."""
    out = []
    for r in raw or []:
        if not isinstance(r, dict) or not str(r.get("do") or "").strip():
            continue
        ids = list(dict.fromkeys(x for x in r.get("events") or [] if x in evs))
        ids = [x for x in ids if evs[x]["level"] != "universal"]
        if not ids:
            continue
        if any(len(set(ids) & b) * 2 >= len(ids) for b in blocked):
            continue
        sess = sorted({evs[x]["session_id"] for x in ids})
        lvl = r.get("level") if r.get("level") in ("personal", "domain_norm") else Counter(
            evs[x]["level"] for x in ids).most_common(1)[0][0]
        out.append({"when": str(r.get("when") or "").strip(), "do": str(r["do"]).strip(),
                    "because": str(r.get("because") or "").strip(), "scope": str(r.get("scope") or "").strip(),
                    "exceptions": str(r.get("exceptions") or "").strip(), "level": lvl, "events": ids,
                    "sessions": sess, "status": "active" if len(ids) >= 2 and len(sess) >= 2 else "candidate"})
    out.sort(key=lambda r: (r["status"] != "active", -len(r["events"]), r["level"] != "personal"))
    return out


def prefix_for(slug: str, used: set[str]) -> str:
    parts = [p for p in slug.split("-") if p] or ["x"]
    cands = ["".join(p[0] for p in parts[:2]).upper(), (parts[0][:2]).upper(),
             "".join(p[0] for p in parts[:3]).upper()]
    for c in cands + [f"{cands[0]}{i}" for i in range(2, 9)]:
        if len(c) >= 2 and c not in used:
            used.add(c)
            return c
    return slug[:3].upper()


def assign_codes(rules: list[dict], prefix: str, prev: list[dict], sep: str = "-") -> None:
    """Mã luật ổn định giữa các lần chạy: giữ mã cũ nếu bằng chứng trùng >= 50% (Jaccard) với luật cũ.

    Mã lĩnh vực dạng KT-07, mã lõi dạng R01 (`sep=""`), theo spec mục 1.1 và 1.2.
    """
    import re
    pat = re.compile(rf"^{re.escape(prefix + sep)}(\d+)$")
    used, taken = set(), set()
    for r in rules:
        best, bj = None, 0.0
        for p in prev:
            if p["code"] in taken or not pat.match(p["code"]):
                continue
            a, b = set(r["events"]), set(p["events"])
            j = len(a & b) / len(a | b) if a | b else 0
            if j > bj:
                best, bj = p, j
        if best is not None and bj >= 0.5:
            r["code"] = best["code"]
            taken.add(best["code"])
            used.add(int(pat.match(best["code"]).group(1)))
    n = 1
    for r in rules:
        if "code" in r:
            continue
        while n in used:
            n += 1
        r["code"] = f"{prefix}{sep}{n:02d}"
        used.add(n)


def check_cases(raw: list[dict], evs: dict[str, dict], k: int) -> list[dict]:
    out = []
    for c in raw or []:
        if isinstance(c, dict) and c.get("event") in evs and str(c.get("action") or "").strip():
            out.append({f: str(c.get(f) or "").strip() for f in
                        ("event", "context", "cue", "judgment", "action", "exception", "outcome")})
    return out[:k]


def check_conflicts(raw: list[dict], evs: dict[str, dict]) -> list[dict]:
    out = []
    for c in raw or []:
        if not isinstance(c, dict) or not str(c.get("question") or "").strip():
            continue
        a = [x for x in c.get("events_a") or [] if x in evs]
        b = [x for x in c.get("events_b") or [] if x in evs]
        if a and b:
            out.append({"events_a": a, "events_b": b, "question": str(c["question"]).strip()})
    return out


# ---------- playbook ----------

def playbook_groups(moves: list[dict], domain: str, min_sessions: int, exclude: set[str]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = defaultdict(list)
    for m in moves:
        if m["domain"] == domain and m["session_id"] not in exclude:
            g[m["task_type"]].append(m)
    return {t: ms for t, ms in g.items() if len(ms) >= min_sessions}


def playbook_prompt(name: str, groups: dict[str, list[dict]], task_names: dict[str, str],
                    fails: dict[str, list[str]]) -> str:
    defs = "; ".join(f"{k} = {v}" for k, v in MOVE_DEF.items())
    parts = []
    for t, ms in groups.items():
        seqs = "\n".join(f"  - ({m['n_user_turns']} lượt) " + " → ".join(m["moves"]) for m in ms)
        fx = "\n".join(f"  - {w}" for w in fails.get(t, [])[:10]) or "  - (không có)"
        parts.append(f"TASK_TYPE {t} ({task_names.get(t, t)}), {len(ms)} sessions. Move sequences:\n{seqs}\n"
                     f"  Corrections the person made in these sessions:\n{fx}")
    return (
        f"These are move sequences of one person working with AI in the field \"{name}\". Moves: {defs}.\n"
        "For each TASK_TYPE write the playbook this person usually follows, in Vietnamese: steps (4 to 8 short "
        "imperative steps an AI should follow to work the way this person does), stop_when (when the work is done), "
        "when_ai_fails (what the person does or expects when the AI gets it wrong). Describe only patterns that "
        "repeat across sessions.\n\n<data>\n" + "\n\n".join(parts) + "\n</data>\n\n"
        "Return JSON exactly like: {\"playbooks\": [{\"task_type\": \"...\", \"steps\": [\"...\"], "
        "\"stop_when\": \"...\", \"when_ai_fails\": \"...\"}]}"
    )


# ---------- văn phong ----------

def style_stats(texts: list[str]) -> dict:
    import re
    n = len(texts) or 1
    toks = [len(t.split()) for t in texts]
    langs = Counter(detect_lang(t) for t in texts)
    first = Counter((re.findall(r"[^\W\d_]+", t.lower()) or [""])[0] for t in texts)
    return {"n_turns": len(texts), "median_words": statistics.median(toks) if toks else 0,
            "p90_words": sorted(toks)[int(0.9 * (len(toks) - 1))] if toks else 0,
            "lang_share": {k: round(v / n, 2) for k, v in langs.items()},
            "question_share": round(sum("?" in t for t in texts) / n, 2),
            "greeting_or_thanks_share": round(sum(bool(re.search(r"(cảm ơn|cám ơn|thanks|thank you|chào|hello|hi\b)",
                                                                 t, re.I)) for t in texts) / n, 2),
            "numbered_list_share": round(sum(len(re.findall(r"^\s*(\d+[.)]|[-*•])\s", t, re.M)) >= 2
                                             for t in texts) / n, 2),
            "top_first_words": [w for w, _ in first.most_common(12) if w]}


def style_prompt(stats: dict, samples: list[str], events: list[dict]) -> str:
    ev = "\n".join(event_line(e) for e in events) or "(không có)"
    sm = "\n".join(f"- {s}" for s in samples)
    return (
        "Below: statistics of how one person writes to AI assistants, sample messages (verbatim), and the times they "
        "corrected the AI's tone or structure.\n"
        "Write a style guide, in Vietnamese, of imperatives telling an AI assistant how to write and communicate when "
        "working by this person's standards: language and mixing of English terms, length, structure, tone, how to "
        "handle short commands. Base every item on the data, and keep only what differs from a typical AI user "
        "(a typical user writes polite full sentences in one language and accepts long generic answers). No "
        "adjective-only items: each item is a concrete instruction. Each item needs an example: a SHORT verbatim "
        "quote (at most 25 words) copied exactly from the sample messages or event quotes, and the event ids it "
        "relies on (may be empty). 6 to 15 items, most important first.\n\n"
        f"<data>\nSTATS: {stats}\n\nSAMPLE MESSAGES:\n{sm}\n\nTONE/STRUCTURE CORRECTIONS:\n{ev}\n</data>\n\n"
        "Return JSON exactly like: {\"style\": [{\"rule\": \"...\", \"example\": \"...\", \"events\": []}]}"
    )


def check_style(raw: list[dict], corpus: list[str], evs: dict[str, dict]) -> list[dict]:
    out = []
    for s in raw or []:
        if not isinstance(s, dict) or not str(s.get("rule") or "").strip():
            continue
        ex = str(s.get("example") or "").strip().strip('"“”')
        if not ex or len(ex.split()) > 40 or not any(is_substring(ex, t) for t in corpus):
            continue
        out.append({"rule": str(s["rule"]).strip(), "example": ex,
                    "events": [x for x in s.get("events") or [] if x in evs]})
    return out


# ---------- lõi chung, câu trả lời mẫu ----------

def rule_line(r: dict, domain: str) -> str:
    return f"{r['code']} [{domain}] Khi {r['when']}, {r['do']} Vì {r['because']}"


def core_prompt(lines: list[str]) -> str:
    return (
        "Below are standards one person enforces on AI answers, grouped by field (code [field] rule).\n"
        "Find standards that appear in TWO OR MORE different fields (same idea, maybe different words). For each, "
        "write one general rule in Vietnamese: when, do (concrete imperative), because, and members (the codes it "
        "merges, from at least two fields). Only real overlaps; it is fine to return few or none.\n\n"
        "<data>\n" + "\n".join(lines) + "\n</data>\n\n"
        "Return JSON exactly like: {\"core\": [{\"when\": \"...\", \"do\": \"...\", \"because\": \"...\", "
        "\"members\": [\"XX-01\", \"YY-03\"]}]}"
    )


def exemplar_prompt(name: str, rules: list[dict], cases: list[dict], k: int = 3) -> str:
    rl = "\n".join(f"{r['code']}: Khi {r['when']}, {r['do']}" for r in rules[:12])
    cs = "\n".join(f"- {c['context']} | dấu hiệu: {c['cue']} | nên: {c['action']}" for c in cases[:5])
    return (
        f"Below are the standards one person enforces on AI answers in the field \"{name}\", and typical cases.\n"
        f"Write {k} exemplars, in Vietnamese: a realistic but invented user question in this field and an answer that "
        "meets these standards (at most 250 words), plus the rule codes the answer applies. Invent all content: no "
        "names, numbers, files or projects from the cases.\n\n"
        f"<data>\nRULES:\n{rl}\n\nCASES:\n{cs}\n</data>\n\n"
        "Return JSON exactly like: {\"exemplars\": [{\"question\": \"...\", \"answer\": \"...\", \"rules\": [\"XX-01\"]}]}"
    )


# ---------- chạy ----------

def run(cfg, llm, sessions, events: list[dict], moves: list[dict], dom_info: dict, chosen: list[str],
        holdout_sessions: set[str], review: dict, holdout_events: set[str] | None = None) -> dict:
    """Lượt giữ lại cho Bước 6 (`holdout_events`) không vào tổng hợp. Playbook và văn phong bỏ cả phiên giữ lại."""
    st = settings(cfg)
    names = {g["slug"]: g["name"] for g in dom_info["domains"]}
    thin = {g["slug"] for g in dom_info["domains"] if g["thin"]}
    task_names = {g["slug"]: g["name"] for g in dom_info["task_types"]}
    prev = read_json(work_dir(cfg) / "synth.json", {}) or {}
    prev_rules = [r for d in (prev.get("domains") or {}).values() for r in d.get("rules", []) + d.get("candidates", [])]
    blocked = [set(x["events"]) for x in review.get("deleted", [])]
    answers = review.get("answers", [])

    hold_ev = holdout_events if holdout_events is not None else {
        e["event_id"] for e in events if e["session_id"] in holdout_sessions}
    train = [e for e in events if e["event_id"] not in hold_ev]
    evs = {e["event_id"]: e for e in train}
    by_dom: dict[str, list[dict]] = defaultdict(list)
    for e in train:
        if e["level"] in ("personal", "domain_norm"):
            by_dom[e["domain"]].append(e)
    doms = [d for d in chosen if by_dom.get(d)]

    # ---- đợt A ----
    pa = ask_many(llm, role(cfg, "strong"),
                  [rules_prompt(names[d], sorted(by_dom[d], key=lambda e: e["event_id"]),
                                [a for a in answers if a.get("domain") == d]) for d in doms],
                  tag="synth", workers=st["workers"], check=_rules_ok, max_tokens=12000)
    pb_doms, pb_prompts = [], []
    for d in doms:
        if d in thin:
            continue
        g = playbook_groups(moves, d, st["playbook_min_sessions"], holdout_sessions)
        if g:
            fails = defaultdict(list)
            for e in train:
                if e["domain"] == d and e["type"] != "accept_explicit" and e.get("want"):
                    fails[e["task_type"]].append(e["want"])
            pb_doms.append((d, g))
            pb_prompts.append(playbook_prompt(names[d], g, task_names, fails))
    pp = ask_many(llm, role(cfg, "strong"), pb_prompts, tag="playbook", workers=st["workers"],
                  check=lambda x: isinstance(x.get("playbooks"), list), max_tokens=6000)
    by_sid = {s.session_id: s for s in sessions}
    sids = sorted({e["session_id"] for e in events} | {
        s.session_id for s in sessions if dom_info["sessions"].get(s.session_id, {}).get("domain") in chosen})
    # thứ tự cố định (sorted): prompt giống hệt giữa các lần chạy thì mới trúng cache
    texts = [t.text for sid in sids if sid in by_sid and sid not in holdout_sessions
             for t in by_sid[sid].active_turns if t.role == "user"]
    short = sorted((t for t in texts if 3 <= len(t.split()) <= 60), key=lambda t: stable("style", t))[:50]
    sty_ev = [e for e in train if {"tone_style", "structure_format"} & set(e.get("aspects") or [])][:40]
    ps = ask_many(llm, role(cfg, "strong"), [style_prompt(style_stats(texts), [clip(norm_ws(t), 300) for t in short],
                                                          sty_ev)],
                  tag="style", workers=1, check=lambda x: isinstance(x.get("style"), list), max_tokens=6000)
    n_pending = pa.pending + pp.pending + ps.pending
    if n_pending:
        raise NeedAgents("Bước 5 đợt A (luật, playbook, văn phong)", n_pending)

    used: set[str] = set()
    out_dom: dict[str, dict] = {}
    for d, ans in zip(doms, pa.answers):
        ans = ans or {}
        rules = check_rules(ans.get("rules"), {k: v for k, v in evs.items() if v["domain"] == d}, blocked)
        assign_codes(rules, prefix_for(d, used), prev_rules)
        dev = {k: v for k, v in evs.items() if v["domain"] == d}
        out_dom[d] = {"name": names[d], "thin": d in thin, "n_sessions": next(
            g["n_sessions"] for g in dom_info["domains"] if g["slug"] == d),
            "n_events": len(by_dom[d]),
            "rules": [r for r in rules if r["status"] == "active"],
            "candidates": [r for r in rules if r["status"] != "active"],
            "conflicts": check_conflicts(ans.get("conflicts"), dev),
            "cases": check_cases(ans.get("cases"), dev, st["max_cases"]), "playbooks": [], "exemplars": []}
    for (d, g), ans in zip(pb_doms, pp.answers):
        for p in (ans or {}).get("playbooks") or []:
            if isinstance(p, dict) and p.get("task_type") in g and p.get("steps"):
                out_dom[d]["playbooks"].append({"task_type": p["task_type"], "name": task_names.get(p["task_type"], p["task_type"]),
                                                "n_sessions": len(g[p["task_type"]]),
                                                "steps": [str(x) for x in p["steps"]][:10],
                                                "stop_when": str(p.get("stop_when") or ""),
                                                "when_ai_fails": str(p.get("when_ai_fails") or "")})
    corpus = short + [e["quote"] for e in sty_ev] + texts
    style = check_style((ps.answers[0] or {}).get("style"), corpus, evs)

    # ---- đợt B ----
    lines = [rule_line(r, d) for d, x in out_dom.items() for r in x["rules"]]
    n_dom_with_rules = sum(1 for x in out_dom.values() if x["rules"])
    pc_ = ask_many(llm, role(cfg, "strong"), [core_prompt(lines)] if n_dom_with_rules >= 2 else [], tag="core",
                   workers=1, check=lambda x: isinstance(x.get("core"), list), max_tokens=6000)
    ex_doms = [d for d, x in out_dom.items() if x["rules"] and not x["thin"]]
    k_ex = max(1, min(3, st["max_exemplars"] // max(1, len(ex_doms))))
    pe = ask_many(llm, role(cfg, "strong"), [exemplar_prompt(out_dom[d]["name"], out_dom[d]["rules"],
                                                             out_dom[d]["cases"], k_ex) for d in ex_doms],
                  tag="exemplars", workers=st["workers"], check=lambda x: isinstance(x.get("exemplars"), list),
                  max_tokens=6000)
    if pc_.pending + pe.pending:
        raise NeedAgents("Bước 5 đợt B (lõi chung, câu trả lời mẫu)", pc_.pending + pe.pending)

    code2 = {r["code"]: (d, r) for d, x in out_dom.items() for r in x["rules"]}
    core = []
    for c in ((pc_.answers or [None])[0] or {}).get("core") or []:
        if not isinstance(c, dict):
            continue
        mem = [m for m in dict.fromkeys(c.get("members") or []) if m in code2]
        if len({code2[m][0] for m in mem}) < 2 or not str(c.get("do") or "").strip():
            continue
        ids = list(dict.fromkeys(x for m in mem for x in code2[m][1]["events"]))
        core.append({"when": str(c.get("when") or "").strip(), "do": str(c["do"]).strip(),
                     "because": str(c.get("because") or "").strip(), "members": mem, "events": ids,
                     "sessions": sorted({evs[x]["session_id"] for x in ids}),
                     "level": Counter(code2[m][1]["level"] for m in mem).most_common(1)[0][0],
                     "domains": sorted({code2[m][0] for m in mem}), "status": "active"})
    core.sort(key=lambda r: -len(r["events"]))
    core = core[:st["max_core_rules"]]
    prev_core = prev.get("core") or []
    assign_codes(core, "R", [p for p in prev_core if "code" in p], sep="")
    in_core = {m: c["code"] for c in core for m in c["members"]}
    for d, x in out_dom.items():
        for r in x["rules"]:
            if r["code"] in in_core:
                r["in_core"] = in_core[r["code"]]
    for d, ans in zip(ex_doms, pe.answers):
        for e in (ans or {}).get("exemplars") or []:
            if isinstance(e, dict) and str(e.get("answer") or "").strip():
                out_dom[d]["exemplars"].append({"question": str(e.get("question") or ""), "answer": str(e["answer"]),
                                                "rules": [c for c in e.get("rules") or [] if c in code2]})
    out = {"domains": out_dom, "core": core, "style": style, "holdout_sessions": sorted(holdout_sessions),
           "holdout_events": sorted(hold_ev),
           "n_events_train": len(train)}
    write_json(work_dir(cfg) / "synth.json", out)
    return out
