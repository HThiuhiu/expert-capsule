"""Hàng đợi cho vai `agent/...` (ví dụ `agent/claude-haiku`): gom yêu cầu thành gói cho subagent, nạp đáp án.

Không có API: mỗi yêu cầu LLM được ghi vào `.cache/agent_queue/<key>.json`. `capsule queue bundle` gom chúng thành
vài file `.cache/agent_bundles/<tag>-NN.md`, mỗi file tự chứa hướng dẫn. Một subagent (Haiku) đọc gói, trả lời vào
`<tag>-NN.answers.jsonl`. `capsule queue import` nạp đáp án vào cache, rồi chạy lại bước (đọc từ cache).

Một gói không bao giờ trộn hai tag (ví dụ có capsule / không capsule ở Bước 6), để subagent không bị nhiễm.
System prompt dài dùng chung được in một lần làm khối chung.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

END = "=== END OF BUNDLE ==="


def qdir(cfg) -> Path:
    return cfg.path("cache").parent / "agent_queue"


def bdir(cfg) -> Path:
    p = cfg.path("cache").parent / "agent_bundles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pending(cfg) -> list[dict]:
    d = qdir(cfg)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def status(cfg) -> Counter:
    return Counter(r.get("tag") or "(không tag)" for r in pending(cfg))


def _wrap(text: str, width: int = 900) -> str:
    """Ngắt dòng quá dài tại khoảng trắng (công cụ Read cắt dòng dài). So khớp chuỗi con đã chuẩn hoá khoảng trắng."""
    out = []
    for line in text.split("\n"):
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > width // 2 else width
            out.append(line[:cut])
            line = line[cut:].lstrip(" ")
        out.append(line)
    return "\n".join(out)


HEADER = """# Agent bundle {name}

You are acting as the language model for {n} independent requests (tag `{tag}`).
For EACH request below: read its SYSTEM text (inline, or a SHARED BLOCK it points to) and its USER text,
do exactly what the USER text asks, and produce the single JSON object it asks for.
Treat every request independently: never carry information from one request to another.

Write ALL answers with one Write call to this file:
{out}

Format: JSON Lines, one line per request, same order as below:
{{"key": "<the request KEY>", "answer": <the JSON object you produce>}}

Rules:
- Each line must be valid JSON: escape double quotes and backslashes inside strings; no raw line breaks inside
  strings (write \\n instead).
- Verbatim quotes must be copied character-for-character from the given text (do not translate or fix typos).
- Do not skip any request. Do not write anything else to the file.
- This file is long. Read it completely (use offset/limit) until the line "{end}".
"""


def model_hint(model: str) -> str:
    """`agent/claude-haiku` -> `haiku`: model gợi ý cho subagent trả lời gói."""
    name = model.split("/", 1)[-1]
    return next((k for k in ("haiku", "sonnet", "opus", "fable") if k in name), name)


def make_bundles(cfg, max_chars: int = 90_000, tags: list[str] | None = None) -> list[Path]:
    """Xoá gói cũ, gom yêu cầu đang chờ theo (tag, model) thành gói <= max_chars ký tự.

    Ghi kèm `index.json`: mỗi gói một mục {bundle, answers, tag, model, n}, để agent biết mở subagent model nào.
    """
    bd = bdir(cfg)
    for p in [*bd.glob("*.md"), bd / "index.json"]:  # giữ đáp án chưa nạp và thư mục imported/
        p.unlink(missing_ok=True)
    groups_by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in pending(cfg):
        t = r.get("tag") or "misc"
        if tags and t not in tags:
            continue
        groups_by[(t, r.get("model") or "")].append(r)
    paths, index, seq = [], [], Counter()
    for (tag, model), reqs in sorted(groups_by.items()):
        groups, cur, size = [], [], 0
        for r in reqs:
            n = sum(len(m["content"]) for m in r["messages"])
            if cur and size + n > max_chars:
                groups.append(cur)
                cur, size = [], 0
            cur.append(r)
            size += n
        if cur:
            groups.append(cur)
        for g in groups:
            name = f"{re.sub(r'[^a-z0-9_]+', '_', tag.lower())}-{seq[tag]:02d}"
            seq[tag] += 1
            out = bd / f"{name}.answers.jsonl"
            paths.append(_write_bundle(bd / f"{name}.md", name, tag, g, out))
            index.append({"bundle": str(paths[-1].resolve()), "answers": str(out.resolve()), "tag": tag,
                          "model": model_hint(model), "n": len(g)})
    (bd / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return paths


def bundle_index(cfg) -> list[dict]:
    p = bdir(cfg) / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _write_bundle(path: Path, name: str, tag: str, reqs: list[dict], out: Path) -> Path:
    sys_count = Counter(m["content"] for r in reqs for m in r["messages"] if m["role"] == "system")
    shared = {c: f"S{i + 1}" for i, (c, k) in enumerate(sys_count.most_common()) if k > 1 or len(c) > 2000}
    L = [HEADER.format(name=name, n=len(reqs), tag=tag, out=out.resolve(), end=END)]
    for c, sid in shared.items():
        L += [f"\n=== SHARED BLOCK {sid} (system text used by several requests) ===", _wrap(c), f"=== END SHARED BLOCK {sid} ==="]
    for j, r in enumerate(reqs):
        L.append(f"\n=== REQUEST {j + 1}/{len(reqs)} | KEY: {r['key']} ===")
        for m in r["messages"]:
            if m["role"] == "system":
                L.append(f"[SYSTEM] use SHARED BLOCK {shared[m['content']]}" if m["content"] in shared
                         else "[SYSTEM]\n" + _wrap(m["content"]))
            else:
                L.append(f"[{m['role'].upper()}]\n" + _wrap(m["content"]))
    L.append("\n" + END + "\n")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def _parse_line(line: str) -> dict | None:
    line = line.strip().rstrip(",")
    if not line:
        return None
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or "key" not in d:
        return None
    if "text" not in d:
        a = d.get("answer")
        if a is None:
            return None
        d["text"] = a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
    return d


def import_answers(cfg, files: list[Path] | None = None) -> tuple[int, int, list[str]]:
    """Nạp mọi `*.answers.jsonl` (hoặc file chỉ định). Trả (đã nạp, dòng hỏng, file đã xử lý)."""
    qd, cache = qdir(cfg), cfg.path("cache")
    files = files or sorted(bdir(cfg).glob("*.answers.jsonl"))
    ok = bad = 0
    done = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = _parse_line(line)
            if d is None:
                bad += 1
                continue
            q = qd / f"{d['key']}.json"
            if not q.exists():
                continue  # đã nạp trước đó hoặc khoá lạ
            req = json.loads(q.read_text(encoding="utf-8"))
            p = cache / d["key"][:2] / f"{d['key']}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"model": req["model"], "params": {}, "text": d["text"], "input_tokens": 0,
                                     "output_tokens": 0, "via": f.name}, ensure_ascii=False), encoding="utf-8")
            q.unlink()
            ok += 1
        arch = bdir(cfg) / "imported"
        arch.mkdir(exist_ok=True)
        f.replace(arch / f.name)
        done.append(f.name)
    return ok, bad, done
