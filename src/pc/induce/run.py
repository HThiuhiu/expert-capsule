"""`pc induce`: B7 bước 1 + 2. Đọc events.jsonl, chỉ dùng split train, ghi capsule/ và reports/step2_induce.md.

Trước khi ghi đè, bản capsule cũ được chép vào capsule/versions/vN/ (ý từ distilly version_manager).
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..ingest import read_sessions
from ..llm import LLM, Pending
from ..mining.gold import read_jsonl
from .consolidate import consolidate, llm_decider
from .lesson import induce_one
from .render import ledger_md, questions_md, skill_md
from .split import load_or_create

FILES = ("rules.jsonl", "cases.jsonl", "deltas.jsonl", "SKILL.md", "ledger.md", "open_questions.md")


def opts(cfg: Config) -> dict:
    o = {"top_k": 5, "min_events": 3, "min_sessions": 2, "supersede_days": 90, "summary_chars": 3000,
         "skill_name": "persona-capsule"}
    o.update(cfg.raw.get("induce") or {})
    return o


def eligible(ev: dict) -> bool:
    return (ev["feedback"].get("generalizability") or "one_off") != "one_off"


def read_exclude(p: Path) -> set[str]:
    if not p.exists():
        return set()
    return {ln.split("#")[0].strip() for ln in p.read_text(encoding="utf-8").splitlines()} - {""}


@dataclass
class InduceResult:
    splits: dict[str, str]
    split_new: bool
    train_events: list[dict] = field(default_factory=list)
    excluded: int = 0
    cases: list[dict] = field(default_factory=list)
    cands: list[dict] = field(default_factory=list)
    status: Counter = field(default_factory=Counter)
    rules: list[dict] = field(default_factory=list)
    deltas: list[dict] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    n_pending: int = 0
    usage: object = None


def select(cfg: Config) -> tuple[dict[str, str], bool, list[dict], int]:
    inter = cfg.path("interim")
    sessions = read_sessions(inter / "sessions.jsonl")
    splits, new = load_or_create(inter / "splits.json", [(s.session_id, s.created_at) for s in sessions])
    exclude = read_exclude(cfg.path("capsule") / "exclude.txt")
    use = set(opts(cfg).get("splits") or ["train"])
    evs = [e for e in read_jsonl(inter / "events.jsonl") if splits.get(e["session_id"]) in use and eligible(e)]
    kept = [e for e in evs if e["event_id"] not in exclude]
    return splits, new, kept, len(evs) - len(kept)


def run(cfg: Config, workers: int = 8) -> InduceResult:
    splits, new, evs, n_ex = select(cfg)
    res = InduceResult(splits=splits, split_new=new, train_events=evs, excluded=n_ex)
    llm = LLM(cfg.path("cache"))
    role = cfg.model("inducer")
    tts = cfg.raw["taxonomy"]["task_types"]
    o = opts(cfg)

    def job(ev):
        try:
            return ev["event_id"], *induce_one(llm, role, ev, tts)
        except Pending:
            return ev["event_id"], None, None, "pending"
        except Exception as e:  # lỗi mạng/API của một event không làm hỏng cả lần chạy
            return ev["event_id"], None, None, f"error: {type(e).__name__}: {e}"

    with ThreadPoolExecutor(workers) as ex:
        for eid, case, cand, st in ex.map(job, evs):
            res.status[st.split(":")[0]] += 1
            if st == "pending":
                res.n_pending += 1
            elif st.startswith("error"):
                res.errors.append(f"{eid}: {st}")
            if case:
                res.cases.append(case)
                res.cands.append(cand)
    if res.n_pending or res.errors:
        res.usage = llm.usage
        return res  # chưa đủ bài học thì chưa hợp nhất: thứ tự delta phải cố định
    vec = None
    if cfg.raw.get("gpu"):  # B7: truy xuất quy tắc gần nhất bằng embedding `when + task_types` (bge-m3, GPU)
        from ..embed import embedder_from
        emb = embedder_from(cfg)
        keys = {c["source_event_id"]: f"{c['when']} | {' '.join(c['task_types'])}" for c in res.cands}
        emb.ensure(keys.values())
        M = emb.get(list(keys.values()))
        vec = {eid: M[i] for i, eid in enumerate(keys)}
    try:
        res.rules, res.deltas, res.questions = consolidate(
            res.cands, llm_decider(llm, role), o["top_k"], o["min_events"], o["min_sessions"], o["supersede_days"],
            vec)
    except Pending:
        res.n_pending += 1
    res.usage = llm.usage
    return res


def backup(cap: Path) -> Path | None:
    if not (cap / "rules.jsonl").exists():
        return None
    vdir = cap / "versions"
    n = 1 + max([int(p.name[1:]) for p in vdir.glob("v*") if p.name[1:].isdigit()] or [0])
    dst = vdir / f"v{n}"
    dst.mkdir(parents=True)
    for f in FILES:
        if (cap / f).exists():
            shutil.copy2(cap / f, dst / f)
    return dst


def write_capsule(cfg: Config, res: InduceResult) -> Path | None:
    cap = cfg.path("capsule")
    cap.mkdir(parents=True, exist_ok=True)
    old = backup(cap)
    o = opts(cfg)

    def dump(name, rows):
        with open(cap / name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("rules.jsonl", res.rules)
    dump("cases.jsonl", sorted(res.cases, key=lambda c: c["case_id"]))
    dump("deltas.jsonl", res.deltas)
    tts = cfg.raw["taxonomy"]["task_types"]
    (cap / "SKILL.md").write_text(skill_md(res.rules, o["skill_name"], len(res.cases), tts, o["summary_chars"]),
                                  encoding="utf-8")
    titles = {s.session_id: s.title for s in read_sessions(cfg.path("interim") / "sessions.jsonl")}
    (cap / "ledger.md").write_text(ledger_md(res.rules, {c["event_id"]: c for c in res.cases}, titles),
                                   encoding="utf-8")
    (cap / "open_questions.md").write_text(questions_md(res.questions, {r["rule_id"]: r for r in res.rules}),
                                           encoding="utf-8")
    return old


# ---------- báo cáo ----------

def _table(title: str, c: Counter) -> list[str]:
    n = sum(c.values()) or 1
    return [f"| {title} | Số | Tỉ lệ |", "|---|---|---|"] + \
        [f"| {k} | {v} | {v / n:.1%} |" for k, v in c.most_common()] + [""]


def render_report(cfg: Config, res: InduceResult, old: Path | None) -> str:
    sp = Counter(res.splits.values())
    rules = res.rules
    L = ["# Step 2: quy nạp capsule (B7 bước 1 và 2)", "",
         f"Inducer `{cfg.model('inducer')['model']}`. Đầu ra: `capsule/`." +
         (f" Bản trước lưu ở `{old.relative_to(cfg.root).as_posix()}`." if old else ""), "",
         "## Lệch so với spec", "",
         ("- Truy xuất quy tắc gần nhất bằng cosine bge-m3 (GPU) trên `when + task_types`, ngưỡng 0,55."
          if cfg.raw.get("gpu") else "- Truy xuất quy tắc gần nhất bằng độ trùng từ (chưa cấu hình GPU)."),
         f"- Học từ split: {', '.join(opts(cfg).get('splits') or ['train'])}.",
         "- Bước 3 (alignment trên dev) chưa làm: cần nhiệm vụ T3 của Module 2.",
         "- Thêm cổng độc quyền (từ distilly): quy tắc là lời khuyên chung bị loại khỏi SKILL.md, vẫn giữ trong rules.jsonl.",
         "", "## Split (C2)", "",
         f"- train {sp['train']}, dev {sp['dev']}, test {sp['test']} phiên. "
         + ("Mới tạo `splits.json` lần này, từ giờ đóng băng." if res.split_new else "Dùng `splits.json` đã đóng băng."),
         f"- Event train có generalizability khác one_off: {len(res.train_events) + res.excluded} "
         f"(loại theo exclude.txt: {res.excluded}).", "",
         "## Bước 1: bài học", ""]
    L += _table("Trạng thái", res.status)
    if res.n_pending or res.errors:
        L += [f"**Dừng trước bước 2**: {res.n_pending} yêu cầu chờ, {len(res.errors)} lỗi.", ""]
        L += [f"- {e}" for e in res.errors[:20]]
        return "\n".join(L) + "\n"
    L += ["## Bước 2: hợp nhất bằng delta", ""]
    L += _table("Thao tác", Counter(d["op"] for d in res.deltas))
    L += _table("Trạng thái quy tắc", Counter(r["status"] for r in rules))
    live = [r for r in rules if r["status"] != "superseded"]
    L += _table("idiosyncrasy (quy tắc còn hiệu lực)", Counter(r["idiosyncrasy"] for r in live))
    L += [f"- Quy tắc riêng (exclusive): {sum(r['exclusive'] for r in live)} / {len(live)}.",
          f"- Mâu thuẫn chờ bạn: {len(res.questions)} (xem `capsule/open_questions.md`).", ""]
    tt = Counter(t for r in rules if r["status"] == "supported" for t in r["task_types"])
    L += _table("task_type của quy tắc supported", tt) if tt else ["(Chưa có quy tắc supported.)", ""]
    sup = sorted((r for r in rules if r["status"] == "supported"), key=lambda r: -len(r["support_events"]))
    L += ["## Quy tắc supported mạnh nhất", ""]
    L += [f"- `{r['rule_id']}` ({len(r['support_events'])} event, {r['n_sessions']} phiên, {r['idiosyncrasy']}): "
          f"khi {r['when']} → {r['do_or_dont']}" for r in sup[:15]] or ["(Không có.)"]
    L += ["", "## Kiểm tra nghiệm thu (B8)", ""]
    ids = {c["event_id"] for c in res.cases}
    bad = [r["rule_id"] for r in rules if r["status"] == "supported" and not set(r["support_events"]) <= ids]
    L += [f"- Quy tắc supported có support_events trỏ về event tồn tại: {'ĐẠT' if not bad else 'TRƯỢT ' + str(bad)}",
          "", "## Việc kế tiếp (chờ bạn duyệt)", "",
          "1. Đọc `capsule/SKILL.md` và `capsule/ledger.md`. Event nào học sai: ghi id vào `capsule/exclude.txt`.",
          "2. Trả lời `capsule/open_questions.md`.",
          "3. Duyệt xong mới sang Module 2 (eval) và bước 3 alignment.", ""]
    return "\n".join(L)
