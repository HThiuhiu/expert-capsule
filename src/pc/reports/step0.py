"""Báo cáo cổng Step 0 (B1): reports/step0_data.md."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from ..ingest import IngestResult


def _pct(xs: list[int], q: float) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))
    return xs[i]


def _dist_row(name: str, xs: list[int]) -> str:
    return (f"| {name} | {len(xs)} | {min(xs, default=0)} | {_pct(xs, .25)} | {_pct(xs, .5)} | "
            f"{_pct(xs, .75)} | {_pct(xs, .9)} | {max(xs, default=0)} |")


def _bucket(n: int) -> str:
    for hi, lab in [(2, "2"), (4, "3-4"), (9, "5-9"), (19, "10-19"), (49, "20-49")]:
        if n <= hi:
            return lab
    return "50+"


def render(res: IngestResult, gate_min: int = 300, min_user_turns: int = 2) -> str:
    S = res.sessions
    user_turns = [t for s in S for t in s.active_turns if t.role == "user"]
    asst_turns = [t for s in S for t in s.active_turns if t.role == "assistant"]
    off_path = [t for s in S for t in s.turns if not t.on_active_path]
    branched = [s for s in S if s.has_branch]
    user_edits = sum(1 for s in S for t in s.turns if t.role == "user" and t.sibling_count > 1 and t.sibling_rank > 0)
    regens = sum(1 for s in S for t in s.turns if t.role == "assistant" and t.sibling_count > 1 and t.sibling_rank > 0)
    by_src = Counter(s.source for s in S)
    lang = Counter(t.lang for t in user_turns)
    n_user = len(user_turns) or 1
    months = Counter((s.created_at or "unknown")[:7] for s in S)
    buckets = Counter(_bucket(s.n_user_turns) for s in S)
    passed = len(S) >= gate_min

    L: list[str] = []
    L += ["# Step 0: dữ liệu", "",
          f"Tạo lúc {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
          "Văn bản đã che bí mật/PII bằng regex trước khi lưu.", ""]
    L += ["## Cổng Step 0", "",
          f"**{'ĐẠT' if passed else 'CHƯA ĐẠT'}**: {len(S)} phiên nhiều lượt (≥ {min_user_turns} lượt user), "
          f"cần ≥ {gate_min}.", ""]
    L += ["## Tổng quan", "", "| Chỉ số | ChatGPT | Claude | Tổng |", "|---|---|---|---|",
          f"| Hội thoại thô | {res.n_raw['chatgpt']} | {res.n_raw['claude']} | {sum(res.n_raw.values())} |",
          f"| Bị loại (< {min_user_turns} lượt user) | {sum(1 for s in res.dropped_short if s.source == 'chatgpt')} | "
          f"{sum(1 for s in res.dropped_short if s.source == 'claude')} | {len(res.dropped_short)} |",
          f"| Phiên giữ lại | {by_src['chatgpt']} | {by_src['claude']} | {len(S)} |",
          f"| Lượt user (tuyến chính) | {sum(s.n_user_turns for s in S if s.source == 'chatgpt')} | "
          f"{sum(s.n_user_turns for s in S if s.source == 'claude')} | {len(user_turns)} |",
          f"| Lượt assistant (tuyến chính) | | | {len(asst_turns)} |", ""]
    L += [f"- File đã đọc: {len(res.files)}. Hội thoại không nhận dạng: {res.n_unknown}. "
          f"Trùng lặp bỏ qua: {res.n_dup}. Lỗi parse: {len(res.errors)}.", ""]
    if res.errors:
        L += ["Lỗi parse (tối đa 10):", ""] + [f"- `{e[:200]}`" for e in res.errors[:10]] + [""]

    L += ["## Ngôn ngữ lượt user", "", "| Ngôn ngữ | Số lượt | Tỉ lệ |", "|---|---|---|"]
    L += [f"| {k} | {lang[k]} | {lang[k] / n_user:.1%} |" for k in ("vi", "en", "mixed")]
    L += ["", "Phát hiện bằng heuristic dấu tiếng Việt, bỏ khối code. Chỉ dùng để thống kê.", ""]

    L += ["## Nhánh (sửa prompt, regenerate)", "",
          f"- Phiên có nhánh: {len(branched)} ({len(branched) / max(len(S), 1):.1%})",
          f"- Lượt ngoài tuyến chính: {len(off_path)}",
          f"- Lượt user là bản sửa (anh em thứ 2 trở đi): {user_edits}",
          f"- Lượt assistant là bản regenerate: {regens}", ""]

    L += ["## Phân bố độ dài", "",
          "| Đại lượng | n | min | p25 | p50 | p75 | p90 | max |", "|---|---|---|---|---|---|---|---|",
          _dist_row("Lượt user mỗi phiên", [s.n_user_turns for s in S]),
          _dist_row("Token mỗi lượt user", [t.n_tokens for t in user_turns]),
          _dist_row("Token mỗi lượt assistant", [t.n_tokens for t in asst_turns]), "",
          "Token là số xấp xỉ (từ + dấu câu), không phải tokenizer của model.", "",
          "| Lượt user mỗi phiên | Số phiên |", "|---|---|"]
    L += [f"| {b} | {buckets[b]} |" for b in ("2", "3-4", "5-9", "10-19", "20-49", "50+")]
    L += ["", f"- Lượt user có code: {sum(t.has_code for t in user_turns)} "
          f"({sum(t.has_code for t in user_turns) / n_user:.1%})", ""]

    L += ["## Theo tháng", "", "| Tháng | Số phiên |", "|---|---|"]
    L += [f"| {m} | {months[m]} |" for m in sorted(months)]
    L += [""]

    L += ["## Che bí mật/PII", "", "| Loại | Số lần che |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(res.scrub_counts.items())] or []
    if not res.scrub_counts:
        L += ["| (không có) | 0 |"]
    L += [""]

    L += ["## Việc kế tiếp (chờ bạn duyệt)", "",
          "1. Xem số liệu trên. Nếu đạt cổng, Claude đề xuất danh sách đóng 8 đến 15 `task_type`/`domain` (B5) để bạn duyệt.",
          "2. Viết `eval/baselines/self_prompt.md` (15 phút) **trước** khi xem kết quả mining (B2 ở C4, D6.2).",
          "3. Xác nhận model cho từng vai trong `config.yaml`. Chạy `pc mine --estimate` để xem chi phí trước khi mine.", ""]
    return "\n".join(L)

