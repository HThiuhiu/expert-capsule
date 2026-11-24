"""`pc mine`: B2 -> B5. Ghi turn_labels, session_labels, disagreements, events, accepted_firstshot."""
from __future__ import annotations

import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import Config
from ..ingest import read_sessions
from ..llm import LLM, Pending
from ..schema import Session, Turn
from .assemble import session_events
from .common import CORRECTION, group, stable_frac
from .label import call_with_check, label_session_meta, turn_messages
from .prefilter import features
from .verify import confidence, verify_messages

PROBE_RATE = 0.05  # B4: 5% lượt Trung tính có f_branch/f_lex cũng qua verifier


@dataclass
class MineResult:
    sessions: list[Session]
    meta: dict[str, dict] = field(default_factory=dict)
    rows: dict[str, dict] = field(default_factory=dict)        # turn_id -> nhãn lượt
    events: list[dict] = field(default_factory=list)
    firstshot: list[dict] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    n_pending: int = 0
    usage: object = None


def pick_sessions(sessions: list[Session], n: Optional[int]) -> list[Session]:
    if not n:
        return sessions
    return sorted(sessions, key=lambda s: stable_frac("pilot", s.session_id))[:n]


def _prev(path: list[Turn], k: int, role: str) -> Optional[Turn]:
    for t in reversed(path[:k]):
        if t.role == role:
            return t
    return None


REPHRASE_COS = 0.80  # B2


def rephrase_map(cfg: Config, sessions: list[Session]) -> dict[str, bool]:
    """B2 f_rephrase: cosine(lượt user, lượt user trước trên tuyến chính) > 0,80. Embedding bge-m3 trên GPU."""
    from ..embed import embedder_from

    emb = embedder_from(cfg)
    pairs = []
    for s in sessions:
        users = [t for t in s.active_turns if t.role == "user"]
        pairs += [(a, b) for a, b in zip(users, users[1:])]
    emb.ensure([t.text for t in {t.turn_id: t for p in pairs for t in p}.values()])
    if not pairs:
        return {}
    import numpy as np
    A = emb.get([a.text for a, _ in pairs])
    B = emb.get([b.text for _, b in pairs])
    cos = (A * B).sum(1)
    return {b.turn_id: bool(c > REPHRASE_COS) for (_, b), c in zip(pairs, np.asarray(cos))}


def label_one_session(llm: LLM, cfg: Config, s: Session, reph: Optional[dict] = None) -> tuple[dict, list[dict]]:
    tax = cfg.raw["taxonomy"]
    meta = label_session_meta(llm, cfg.model("labeler"), s, tax["task_types"], tax["domains"])
    rows: list[dict] = []
    labels: dict[str, str] = {}
    path = s.active_turns
    for k, t in enumerate(path):
        if t.role != "user":
            continue
        prev_asst = _prev(path, k, "assistant")
        row = {"session_id": s.session_id, "turn_id": t.turn_id, "idx": t.idx,
               "features": features(s, t, prev_asst, (reph or {}).get(t.turn_id)) if t.idx > 0 else None}
        if t.idx == 0 or prev_asst is None:
            row.update(labeler={"primary_label": None, "move": meta["first_move"]}, status="first_turn")
            rows.append(row)
            continue
        # yêu cầu gốc gần nhất theo nhãn labeler đã có (đi ngược qua các lượt Sửa sai)
        req = None
        for u in reversed(path[:k]):
            if u.role == "user" and labels.get(u.turn_id) not in CORRECTION:
                req = u
                break
        lab, status = call_with_check(llm, cfg.model("labeler"),
                                      lambda note: turn_messages(req, prev_asst, t, note), t, prev_asst)
        labels[t.turn_id] = lab["primary_label"]
        row.update(labeler=lab, status=status)
        rows.append(row)
    return meta, rows


def verify_one(llm: LLM, cfg: Config, s: Session, row: dict) -> dict:
    path = s.active_turns
    k = next(i for i, t in enumerate(path) if t.turn_id == row["turn_id"])
    t, prev_asst = path[k], _prev(path, k, "assistant")
    try:
        lab, status = call_with_check(llm, cfg.model("verifier"),
                                      lambda note: verify_messages(s, t, prev_asst, note), t, prev_asst,
                                      include_move=False)
    except Pending:
        return {"status": "pending"}
    return {"status": status, "label": lab}


def run(cfg: Config, pilot: Optional[int] = None, skip_verify: bool = False, workers: int = 8) -> MineResult:
    sessions = pick_sessions(read_sessions(cfg.path("interim") / "sessions.jsonl"), pilot)
    res = MineResult(sessions=sessions)
    llm = LLM(cfg.path("cache"))
    by_sid = {s.session_id: s for s in sessions}
    reph = rephrase_map(cfg, sessions) if cfg.raw.get("gpu") else {}

    # B2 + B3
    def job(s: Session):
        try:
            return s.session_id, *label_one_session(llm, cfg, s, reph), None
        except Exception as e:  # lỗi mạng/API của một phiên không làm hỏng cả lần chạy
            return s.session_id, None, [], f"{s.session_id}: {type(e).__name__}: {e}"

    with ThreadPoolExecutor(workers) as ex:
        for sid, meta, rows, err in ex.map(job, sessions):
            if err:
                res.errors.append(err)
                continue
            res.meta[sid] = meta
            for r in rows:
                res.rows[r["turn_id"]] = r

    # B4
    targets, probes = [], []
    for r in res.rows.values():
        p = (r.get("labeler") or {}).get("primary_label")
        if p is None:
            continue
        if p in CORRECTION or p == "accept_explicit":
            targets.append(r)
        elif group(p) == "neutral" and (r["features"]["f_branch"] or r["features"]["f_lex"]) \
                and stable_frac("probe", r["turn_id"]) < PROBE_RATE:
            probes.append(r)
    if not skip_verify:
        def vjob(r):
            try:
                return r["turn_id"], verify_one(llm, cfg, by_sid[r["session_id"]], r)
            except Exception as e:
                return r["turn_id"], {"status": "error", "error": f"{type(e).__name__}: {e}"}

        with ThreadPoolExecutor(workers) as ex:
            for tid, v in ex.map(vjob, targets + probes):
                res.rows[tid]["verifier"] = v
                if v["status"] == "error":
                    res.errors.append(f"verify {tid}: {v['error']}")
    for r in probes:
        r["probe"] = True
    target_ids = {r["turn_id"] for r in targets}

    # nhãn cuối
    final: dict[str, dict] = {}
    for tid, r in res.rows.items():
        lab = r.get("labeler") or {}
        p = lab.get("primary_label")
        v = r.get("verifier") or {}
        if p is None:
            r["confidence"] = "n/a"
            final[tid] = {"label": None, "confidence": "n/a"}
            continue
        if r.get("probe"):
            r["confidence"] = "n/a"
            if v.get("status") not in (None, "pending", "error") and group(v["label"]["primary_label"]) == "correction":
                res.disagreements.append({"kind": "probe_missed", "turn_id": tid, "session_id": r["session_id"],
                                          "labeler": p, "verifier": v["label"]["primary_label"]})
            final[tid] = {"label": lab, "confidence": "n/a"}
            continue
        if tid in target_ids and v.get("label"):
            c = confidence(p, v["label"]["primary_label"])
            r["confidence"] = c
            if c == "dropped":
                res.disagreements.append({"kind": "dropped", "turn_id": tid, "session_id": r["session_id"],
                                          "labeler": p, "verifier": v["label"]["primary_label"]})
            label = None if c == "dropped" else (lab if c == "high" else {**v["label"], "move": lab.get("move")})
            final[tid] = {"label": label, "confidence": c}
        else:
            if v.get("status") == "pending":
                res.n_pending += 1
            r["confidence"] = "unverified" if tid in target_ids else "n/a"
            final[tid] = {"label": lab, "confidence": r["confidence"]}

    # B5
    for s in sessions:
        if s.session_id not in res.meta:
            continue
        ev, fs = session_events(s, final, res.meta[s.session_id])
        res.events += ev
        res.firstshot += fs
    res.usage = llm.usage
    return res


def write_outputs(res: MineResult, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def dump(name, rows):
        with open(out / name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("session_labels.jsonl", res.meta.values())
    dump("turn_labels.jsonl", res.rows.values())
    dump("disagreements.jsonl", res.disagreements)
    dump("events.jsonl", res.events)
    dump("accepted_firstshot.jsonl", res.firstshot)


# ---------- báo cáo ----------

def _table(title: str, c: Counter, total: Optional[int] = None) -> list[str]:
    n = total or sum(c.values()) or 1
    L = [f"| {title} | Số | Tỉ lệ |", "|---|---|---|"]
    L += [f"| {k} | {v} | {v / n:.1%} |" for k, v in c.most_common()]
    return L + [""]


def render(res: MineResult, cfg: Config, pilot: Optional[int], out: Path) -> str:
    rows = [r for r in res.rows.values() if (r.get("labeler") or {}).get("primary_label")]
    prim = Counter(r["labeler"]["primary_label"] for r in rows)
    grp = Counter(group(r["labeler"]["primary_label"]) for r in rows)
    status = Counter(r["status"] for r in rows)
    moves = Counter((r.get("labeler") or {}).get("move") for r in res.rows.values())
    conf = Counter(r.get("confidence") for r in rows if r.get("confidence") != "n/a")
    vstat = Counter((r.get("verifier") or {}).get("status", "chưa chạy") for r in rows
                    if r.get("confidence") != "n/a" or r.get("probe"))
    ev = res.events
    ev_lab = Counter(e["feedback"]["primary_label"] for e in ev)
    ev_idio = Counter(e["feedback"]["idiosyncrasy"] for e in ev)
    ev_gen = Counter(e["feedback"]["generalizability"] for e in ev)
    ev_out = Counter(e["outcome"] for e in ev)
    ev_conf = Counter(e["confidence"] for e in ev)
    tt = Counter(m["task_type"] for m in res.meta.values())
    feats = Counter(k for r in rows for k, v in (r["features"] or {}).items() if v)
    probes = [r for r in res.rows.values() if r.get("probe")]
    missed = sum(1 for d in res.disagreements if d["kind"] == "probe_missed")
    lab_m, ver_m = cfg.model("labeler")["model"], cfg.model("verifier")["model"]
    u = res.usage

    L = [f"# Step 1: mining {'(CHẠY THỬ ' + str(pilot) + ' phiên)' if pilot else ''}", "",
         f"Đầu ra: `{out.as_posix()}`. Labeler `{lab_m}`, verifier `{ver_m}`.", ""]
    L += ["## Lệch so với spec", "",
          "- `f_rephrase` (B2): bge-m3 trên GPU server, ngưỡng cosine 0,80." if cfg.raw.get("gpu")
          else "- `f_rephrase` (B2) chưa tính: chưa cấu hình GPU embedding.",
          f"- Verifier là `{ver_m}`. Spec B4 muốn model mạnh." if "haiku" in ver_m else "",
          "- `task_type`/`domain` dùng danh sách tạm (config `taxonomy`), bạn chưa duyệt chính thức (B5).",
          "- Chưa có tập gold nên chưa chấm G1 (B6).", ""]
    L += ["## Khối lượng", "",
          f"- Phiên: {len(res.meta)} / {len(res.sessions)} (lỗi {len(res.errors)}). Lượt user được gán (idx > 0): {len(rows)}.",
          f"- Lệnh gọi LLM mới: {u.calls}, cache hit: {u.cache_hits}, token vào/ra: {u.input_tokens}/{u.output_tokens}.",
          f"- Yêu cầu verifier đang chờ subagent: {res.n_pending}.", ""]
    if res.errors:
        L += ["Lỗi (tối đa 10):", ""] + [f"- `{e[:300]}`" for e in res.errors[:10]] + [""]
    L += ["## Nhãn labeler (B3)", ""] + _table("Nhóm", grp) + _table("Nhãn chính", prim)
    L += _table("Trạng thái kiểm tra span", status)
    L += _table("Move (mọi lượt user, kể cả lượt đầu)", moves)
    L += _table("Đặc trưng B2 bật", feats, len(rows))
    L += ["## Kiểm chứng (B4)", ""] + _table("Trạng thái verifier", vstat) + _table("Mức tin cậy", conf)
    L += [f"- Lượt dò sót (5% Trung tính có f_branch/f_lex): {len(probes)}, verifier nói là Sửa sai: {missed}.", ""]
    L += ["## Correction events (B5)", "", f"- Tổng: {len(ev)}. accepted_firstshot: {len(res.firstshot)}.", ""]
    L += _table("Nhãn", ev_lab) + _table("idiosyncrasy", ev_idio) + _table("generalizability", ev_gen)
    L += _table("outcome", ev_out) + _table("confidence", ev_conf)
    L += ["## task_type của phiên", ""] + _table("task_type", tt)
    personal = sum(1 for e in ev if e["feedback"]["idiosyncrasy"] == "personal")
    non_one_off = sum(1 for e in ev if e["feedback"]["generalizability"] not in (None, "one_off"))
    L += ["## Số lượng cho cổng G1 (B6)", "",
          f"- Event `generalizability` khác `one_off`: {non_one_off} (G1 cần ≥ 150).",
          f"- Event `personal`: {personal} (G1 cần ≥ 60).",
          "- Precision/recall cần tập gold: chạy `pc gold` (chưa làm).", ""]
    return "\n".join(x for x in L if x is not None)


def examples_md(res: MineResult, n: int = 20, seed: int = 0) -> str:
    """B8: 20 event ngẫu nhiên in đầy đủ để bạn đọc."""
    ev = list(res.events)
    random.Random(seed).shuffle(ev)
    L = ["# 20 event ngẫu nhiên", "", "Đọc **sau** khi đã viết `eval/baselines/self_prompt.md`.", ""]
    for e in ev[:n]:
        f = e["feedback"]
        L += [f"## {e['event_id']}", "",
              f"`{f['primary_label']}` · aspects {f['aspects']} · {f['generalizability']} · {f['idiosyncrasy']} · "
              f"outcome {e['outcome']} · {e['confidence']} · task {e['task']['task_type']}", "",
              "**Yêu cầu**", "", "```", e["task"]["request_text"][:1500], "```", "",
              "**Câu trả lời bị bác**", "", "```", e["rejected_text"][:1500], "```", "",
              "**Phản hồi**", "", "```", e["feedback_text"][:1500], "```", "",
              f"evidence_span: `{f['evidence_span']}`", ""]
    return "\n".join(L)
