"""Bước 2: gán lĩnh vực (LLM rẻ) rồi gộp nhãn gần nghĩa (LLM mạnh, một lệnh) và đề xuất danh sách để chọn.

Đầu vào mỗi phiên: tiêu đề + 3 lượt user đầu (cắt gọn, khoảng 500 token). Gom `batch_domains` phiên mỗi lệnh gọi
để giảm chi phí (spec ghi một lệnh mỗi phiên; gom lô cho cùng nội dung, rẻ hơn).
Đầu ra `data/lite/domains.json`: lĩnh vực chuẩn, task_type chuẩn, nhãn của từng phiên, cờ "mỏng".
"""
from __future__ import annotations

import json
from collections import Counter

from pc.schema import Session

from .common import NeedAgents, ask_many, base_dir, chunks, clip, read_json, read_jsonl, role, settings, slugify, work_dir, \
    write_json, write_jsonl

OTHER = "khac"


def brief(s: Session, n_turns: int = 3, chars: int = 300) -> str:
    users = [t for t in s.active_turns if t.role == "user"][:n_turns]
    body = "\n".join(f"  - {clip(' '.join(t.text.split()), chars)}" for t in users)
    return f"TITLE: {s.title or '(none)'}\n  USER TURNS:\n{body}"


def label_prompt(batch: list[Session]) -> str:
    items = "\n\n".join(f"[s{i + 1}] {brief(s)}" for i, s in enumerate(batch))
    return (
        "For each chat session below give two short labels.\n"
        "- domain: the field of expertise the session is about. 1 to 3 English words, lowercase, general and "
        "reusable (e.g. \"machine learning\", \"macroeconomics\", \"web development\", \"competitive programming\", "
        "\"university coursework\", \"personal finance\"). Not the specific topic.\n"
        "- task_type: the kind of work the user wants from the AI. 1 to 3 English words, lowercase (e.g. \"debug code\", "
        "\"explain concept\", \"write code\", \"review paper\", \"exam prep\", \"write text\", \"plan project\", "
        "\"solve problem\").\n\n"
        f"<data>\n{items}\n</data>\n\n"
        "Return JSON exactly like: {\"sessions\": [{\"id\": \"s1\", \"domain\": \"...\", \"task_type\": \"...\"}, ...]} "
        f"with one entry for each of the {len(batch)} sessions."
    )


def _labels_ok(n: int):
    def check(d: dict) -> bool:
        ids = {str(x.get("id")) for x in d.get("sessions") or [] if isinstance(x, dict)}
        return all(f"s{i + 1}" in ids for i in range(n))
    return check


def run_labels(cfg, llm, sessions: list[Session]) -> list[dict]:
    st = settings(cfg)
    batches = chunks(sessions, st["batch_domains"])
    res = ask_many(llm, role(cfg, "cheap"), [label_prompt(b) for b in batches], tag="domains",
                   workers=st["workers"], check=[_labels_ok(len(b)) for b in batches])
    rows = []
    for b, ans in zip(batches, res.answers):
        got = {str(x.get("id")): x for x in (ans or {}).get("sessions") or [] if isinstance(x, dict)}
        for i, s in enumerate(b):
            x = got.get(f"s{i + 1}") or {}
            if ans is None:
                continue
            rows.append({"session_id": s.session_id,
                         "domain_raw": str(x.get("domain") or "other").strip().lower()[:60],
                         "task_raw": str(x.get("task_type") or "other").strip().lower()[:60]})
    if res.pending:
        raise NeedAgents("Bước 2 (gán lĩnh vực)", res.pending)
    write_jsonl(base_dir(cfg) / "domain_labels.jsonl", rows)
    return rows


def merge_prompt(dom: Counter, task: Counter) -> str:
    d = "\n".join(f"- {k} ({v})" for k, v in dom.most_common())
    t = "\n".join(f"- {k} ({v})" for k, v in task.most_common())
    return (
        "Below are raw labels produced for a person's chat sessions, with session counts.\n"
        "1. Group DOMAIN labels that mean the same field of expertise into canonical domains. Aim for 4 to 12 domains. "
        "A domain must be a field a person could be an expert in (e.g. machine learning, economics, software "
        "engineering, algorithms). Put leftovers into slug \"khac\".\n"
        "2. Group TASK_TYPE labels the same way into 6 to 12 canonical task types. Leftovers go to \"khac\".\n"
        "For each canonical group give: slug (Vietnamese without diacritics, kebab-case, e.g. \"kinh-te-vi-mo\", "
        "\"lap-trinh-web\"), name (short Vietnamese display name with diacritics), members (raw labels copied exactly). "
        "Every raw label must appear in exactly one group.\n\n"
        f"<data>\nDOMAIN LABELS:\n{d}\n\nTASK_TYPE LABELS:\n{t}\n</data>\n\n"
        "Return JSON exactly like: {\"domains\": [{\"slug\": \"...\", \"name\": \"...\", \"members\": [\"...\"]}], "
        "\"task_types\": [{\"slug\": \"...\", \"name\": \"...\", \"members\": [\"...\"]}]}"
    )


def _canon(groups: list[dict], raw: Counter) -> tuple[list[dict], dict[str, str]]:
    """Chuẩn hoá nhóm do LLM trả: slug hợp lệ, không trùng, nhãn thô nào thiếu thì vào `khac`."""
    out, m, seen = [], {}, set()
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        slug = slugify(str(g.get("slug") or g.get("name") or OTHER))
        if slug in seen:
            slug = next(f"{slug}-{i}" for i in range(2, 99) if f"{slug}-{i}" not in seen)
        mem = [x for x in (g.get("members") or []) if isinstance(x, str) and x in raw and x not in m]
        if not mem:
            continue
        seen.add(slug)
        out.append({"slug": slug, "name": str(g.get("name") or slug)[:60], "members": mem})
        for x in mem:
            m[x] = slug
    left = [x for x in raw if x not in m]
    if left:
        g = next((g for g in out if g["slug"] == OTHER), None)
        if g is None:
            g = {"slug": OTHER, "name": "Khác", "members": []}
            out.append(g)
        g["members"] += left
        for x in left:
            m[x] = OTHER
    return out, m


def run_merge(cfg, llm, rows: list[dict]) -> dict:
    st = settings(cfg)
    dom = Counter(r["domain_raw"] for r in rows)
    task = Counter(r["task_raw"] for r in rows)
    res = ask_many(llm, role(cfg, "strong"), [merge_prompt(dom, task)], tag="domains_merge", workers=1,
                   check=lambda d: isinstance(d.get("domains"), list) and isinstance(d.get("task_types"), list),
                   max_tokens=8000)
    if res.pending:
        raise NeedAgents("Bước 2 (gộp nhãn)", res.pending)
    ans = res.answers[0] or {"domains": [], "task_types": []}
    doms, dmap = _canon(ans["domains"], dom)
    tasks, tmap = _canon(ans["task_types"], task)
    sess = {r["session_id"]: {"domain": dmap[r["domain_raw"]], "task_type": tmap[r["task_raw"]]} for r in rows}
    n = Counter(v["domain"] for v in sess.values())
    for g in doms:
        g["n_sessions"] = n.get(g["slug"], 0)
        g["thin"] = g["n_sessions"] < st["thin_sessions"] or g["slug"] == OTHER
    doms.sort(key=lambda g: (g["slug"] == OTHER, -g["n_sessions"]))
    out = {"domains": doms, "task_types": tasks, "sessions": sess}
    write_json(base_dir(cfg) / "domains.json", out)
    return out


def load(cfg) -> dict | None:
    d = read_json(base_dir(cfg) / "domains.json")
    return with_custom(cfg, d) if d else d


# ---------- lĩnh vực tuỳ chỉnh (cắt theo kiểu việc, ví dụ "phong cách nghiên cứu") ----------

def _match(spec: dict, lab: dict, raw: dict) -> bool:
    """Điều kiện trong config `capsule.custom_domains.<slug>`:
    domains / task_types: danh sách slug chuẩn; raw_domain / raw_task: regex trên nhãn thô của Bước 2.
    match: all (mặc định, mọi nhóm điều kiện có ghi đều phải đúng) | any (một nhóm đúng là đủ).
    """
    import re
    tests = []
    if spec.get("domains") or spec.get("raw_domain"):
        tests.append(lab["domain"] in (spec.get("domains") or [])
                     or bool(spec.get("raw_domain") and re.search(spec["raw_domain"], raw.get("domain_raw", ""), re.I)))
    if spec.get("task_types") or spec.get("raw_task"):
        tests.append(lab["task_type"] in (spec.get("task_types") or [])
                     or bool(spec.get("raw_task") and re.search(spec["raw_task"], raw.get("task_raw", ""), re.I)))
    if not tests:
        return False
    return any(tests) if spec.get("match") == "any" else all(tests)


def with_custom(cfg, d: dict) -> dict:
    custom = settings(cfg).get("custom_domains") or {}
    if not custom:
        return d
    raw = {r["session_id"]: r for r in read_jsonl(base_dir(cfg) / "domain_labels.jsonl")}
    thin = settings(cfg)["thin_sessions"]
    out = {**d, "domains": [g for g in d["domains"] if not g.get("custom")], "custom_sessions": {}}
    for slug, spec in custom.items():
        mem = sorted(sid for sid, lab in d["sessions"].items() if _match(spec, lab, raw.get(sid, {})))
        out["custom_sessions"][slug] = mem
        out["domains"].append({"slug": slug, "name": spec.get("name", slug), "members": [], "custom": True,
                               "n_sessions": len(mem), "thin": len(mem) < thin})
    return out


def labels_for(d: dict, chosen: list[str]) -> dict[str, dict]:
    """Nhãn phiên cho một lần build: phiên thuộc lĩnh vực tuỳ chỉnh được chọn thì mang slug đó (lĩnh vực tuỳ chỉnh
    chọn trước thắng), còn lại giữ lĩnh vực gốc."""
    labels = {sid: dict(v) for sid, v in d["sessions"].items()}
    taken: set[str] = set()
    for c in chosen:
        for sid in (d.get("custom_sessions") or {}).get(c, []):
            if sid not in taken:
                labels[sid]["domain"] = c
                taken.add(sid)
    return labels


def run(cfg, llm, sessions: list[Session], force: bool = False) -> dict:
    p = base_dir(cfg) / "domain_labels.jsonl"
    have = {r["session_id"] for r in read_jsonl(p)}
    if force or not have or have != {s.session_id for s in sessions}:
        rows = run_labels(cfg, llm, sessions)
    else:
        rows = read_jsonl(p)
    return run_merge(cfg, llm, rows)


def summary(d: dict) -> str:
    full = [g for g in d["domains"] if not g["thin"] and not g.get("custom")]
    thin = [g for g in d["domains"] if g["thin"]]
    s = f"Phát hiện {len(full)} lĩnh vực: " + ", ".join(f"{g['name']} ({g['n_sessions']} phiên)" for g in full) + "."
    if thin:
        s += "\nMỏng (dưới ngưỡng, chỉ góp vào lõi chung): " + ", ".join(
            f"{g['name']} ({g['n_sessions']})" for g in thin) + "."
    s += "\nChọn lĩnh vực muốn chưng cất: capsule build --domains " + ",".join(g["slug"] for g in full[:3])
    return s


def table(d: dict) -> str:
    L = ["| slug | Lĩnh vực | Phiên | Mỏng | Nhãn thô gộp vào |", "|---|---|---|---|---|"]
    for g in d["domains"]:
        mem = "(tuỳ chỉnh, xem config.local.yaml)" if g.get("custom") else \
            ", ".join(g["members"][:6]) + (" ..." if len(g["members"]) > 6 else "")
        L.append(f"| `{g['slug']}` | {g['name']} | {g['n_sessions']} | {'có' if g['thin'] else ''} | {mem} |")
    return "\n".join(L)


__all__ = ["run", "load", "summary", "table", "brief", "label_prompt", "merge_prompt", "_canon", "json"]
