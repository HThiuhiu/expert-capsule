"""Bước 3: lọc tín hiệu (không gọi LLM). Chấm điểm mọi lượt user, chọn 200 đến 400 lượt điểm cao nhất, chia đều theo
lĩnh vực đã chọn, cộng 10% lượt ngẫu nhiên.

Đặc trưng (trọng số):
- f_branch (3): lượt có nhánh regenerate hoặc nhánh sửa prompt.
- f_lex (2): từ khoá sửa sai tiếng Việt/Anh.
- f_rephrase (2): cosine với lượt user trước > 0,80. Embedding bge-m3 lấy từ cache trên máy; thiếu vector thì bỏ qua
  (không gọi GPU).
- f_short_after_long (1): mệnh lệnh ngắn ngay sau một câu trả lời dài (>= 300 token).
- f_praise (1): khen hoặc xác nhận có nội dung cụ thể.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from pc.mining.prefilter import f_lex, f_short_imperative
from pc.schema import Session, Turn
from pc.textutil import approx_tokens, strip_code

from .common import settings, stable, work_dir, write_jsonl

WEIGHTS = {"f_branch": 3, "f_lex": 2, "f_rephrase": 2, "f_short_after_long": 1, "f_praise": 1}
LONG_ANSWER = 300
REPHRASE_COS = 0.80

_PRAISE = re.compile(
    r"(?<![\w])(tốt|hay|chuẩn|đúng rồi|đúng ý|ổn rồi|tuyệt|xuất sắc|rất ổn|chính xác|great|perfect|exactly|"
    r"nice|good job|well done|love (it|this)|that'?s (it|right)|works)(?![\w])", re.I)


def f_praise(text: str) -> bool:
    t = strip_code(text)
    return bool(_PRAISE.search(t)) and approx_tokens(t) >= 5  # có nội dung cụ thể, không chỉ "ok"


def _cos_lookup(cfg, texts: list[str] | None = None):
    """Trả hàm cos(a, b) -> float | None. Chế độ `capsule.embed`:
    off: không dùng (f_rephrase luôn False); cache: chỉ vector đã có trong .cache/emb;
    local: tính thiếu bằng sentence-transformers trên máy; gpu: tính thiếu trên máy chủ GPU (config gpu, env GPU_PW).
    """
    mode = str(settings(cfg).get("embed") or "off").lower()
    if mode in ("off", "false", "none", "0"):
        return lambda a, b: None
    try:
        from pc.embed import embedder_from
        emb = embedder_from(cfg)
        if mode in ("local", "gpu") and texts:
            emb.ensure(texts, mode=mode)
    except ImportError as e:
        print(f"Bỏ qua f_rephrase: thiếu thư viện ({e}). Cài: pip install -e \".[embed]\"")
        return lambda a, b: None

    def cos(a: str, b: str) -> Optional[float]:
        if not (emb.has(a) and emb.has(b)):
            return None
        A, B = emb.get([a, b])
        return float((A * B).sum())
    return cos


def turn_features(user: Turn, prev_asst: Optional[Turn], prev_user: Optional[Turn], cos=None) -> dict:
    c = cos(prev_user.text, user.text) if (cos and prev_user is not None) else None
    return {
        "f_branch": user.sibling_count > 1 or (prev_asst is not None and prev_asst.sibling_count > 1),
        "f_lex": f_lex(user.text),
        "f_rephrase": bool(c is not None and c > REPHRASE_COS),
        "f_short_after_long": f_short_imperative(user.text) and prev_asst is not None and prev_asst.n_tokens >= LONG_ANSWER,
        "f_praise": f_praise(user.text),
    }


def score(f: dict) -> int:
    return sum(w for k, w in WEIGHTS.items() if f.get(k))


def candidates(sessions: list[Session], labels: dict[str, dict], chosen: set[str], cos=None) -> list[dict]:
    out = []
    for s in sessions:
        lab = labels.get(s.session_id)
        if not lab or lab["domain"] not in chosen:
            continue
        path = s.active_turns
        last_a = last_u = None
        for t in path:
            if t.role == "assistant":
                last_a = t
                continue
            if t.idx > 0 and last_a is not None:
                f = turn_features(t, last_a, last_u, cos)
                out.append({"turn_id": t.turn_id, "session_id": s.session_id, "domain": lab["domain"],
                            "task_type": lab["task_type"], "created_at": s.created_at, "features": f,
                            "score": score(f)})
            last_u = t
    return out


def select(cands: list[dict], chosen: list[str], budget: int, random_frac: float = 0.10, seed: str = "lite") -> list[dict]:
    """Chia đều `budget*(1-random_frac)` theo lĩnh vực cho lượt có điểm > 0; phần còn lại lấy ngẫu nhiên (tái lập)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for c in cands:
        by[c["domain"]].append(c)
    for d in by:
        by[d].sort(key=lambda c: (-c["score"], stable(seed, c["turn_id"])))
    top_n = int(round(budget * (1 - random_frac)))
    picked: dict[str, list[dict]] = {d: [] for d in chosen}
    scored = {d: [c for c in by.get(d, []) if c["score"] > 0] for d in chosen}
    # vòng tròn: mỗi lượt một lĩnh vực, lĩnh vực hết ứng viên thì nhường suất
    while sum(map(len, picked.values())) < top_n and any(len(picked[d]) < len(scored[d]) for d in chosen):
        for d in chosen:
            if sum(map(len, picked.values())) >= top_n:
                break
            if len(picked[d]) < len(scored[d]):
                picked[d].append(scored[d][len(picked[d])])
    out = [dict(c, why="score") for d in chosen for c in picked[d]]
    taken = {c["turn_id"] for c in out}
    rest = {d: sorted((c for c in by.get(d, []) if c["turn_id"] not in taken), key=lambda c: stable(seed, "r", c["turn_id"]))
            for d in chosen}
    k = 0
    while len(out) < budget and any(rest.values()):
        d = chosen[k % len(chosen)]
        if rest[d]:
            out.append(dict(rest[d].pop(0), why="random"))
        k += 1
    return out


def run(cfg, sessions: list[Session], labels: dict[str, dict], chosen: list[str], budget: int,
        random_frac: float) -> list[dict]:
    texts = sorted({t.text for s in sessions if (labels.get(s.session_id) or {}).get("domain") in chosen
                    for t in s.active_turns if t.role == "user"})
    cands = candidates(sessions, labels, set(chosen), _cos_lookup(cfg, texts))
    sel = select(cands, chosen, budget, random_frac)
    write_jsonl(work_dir(cfg) / "selected.jsonl", sel)
    return sel
