"""`capsule build --domains a,b`: Bước 3 đến 6, chế độ Lite. Chạy lại được: phần đã xong đọc từ cache LLM.

Mỗi khi còn yêu cầu chờ subagent (`agent/...`), dừng với NeedAgents; nạp đáp án rồi chạy lại lệnh.
"""
from __future__ import annotations

from collections import Counter

from . import domains as dom_mod
from . import mine, prefilter, quickcheck, review, synthesize
from .common import NeedAgents, read_jsonl, settings, work_dir, write_json


def _stage(*fns):
    """Chạy các hàm độc lập; gộp số yêu cầu chờ của mọi hàm rồi mới dừng."""
    out, pend, names = [], 0, []
    for f in fns:
        try:
            out.append(f())
        except NeedAgents as e:
            out.append(None)
            pend += e.n
            names.append(e.step)
    if pend:
        raise NeedAgents(" + ".join(names), pend)
    return out


def run(cfg, llm, sessions, chosen: list[str], deep: bool = False, turns: int | None = None) -> str:
    if deep:
        raise ValueError("Chế độ Deep dùng pipeline cũ: `pc mine` (nhãn mọi lượt + verifier), xem README. "
                         "So Lite với Deep thuộc giai đoạn 2.")
    st = settings(cfg)
    d = dom_mod.load(cfg)
    if not d:
        raise ValueError("Chưa có danh sách lĩnh vực. Chạy `capsule domains` trước.")
    slugs = {g["slug"] for g in d["domains"]}
    if not chosen:
        raise ValueError(dom_mod.summary(d))
    bad = [c for c in chosen if c not in slugs]
    if bad:
        raise ValueError(f"Không có lĩnh vực: {', '.join(bad)}. Xem `capsule domains`.")
    budget = turns or st["turns"]
    write_json(work_dir(cfg) / "build.json", {"domains": chosen, "turns": budget})
    labels = dom_mod.labels_for(d, chosen)   # lĩnh vực tuỳ chỉnh được chọn thì cắt lại phiên
    d = {**d, "sessions": labels}
    by_sid = {s.session_id: s for s in sessions}

    # Bước 3
    sel = prefilter.run(cfg, sessions, labels, chosen, budget, st["random_frac"])
    # Bước 4
    events, moves = _stage(lambda: mine.run_mine(cfg, llm, sessions, sel),
                           lambda: mine.run_moves(cfg, llm, sessions, labels, chosen))
    # Bước 6 (chọn trước phần giữ lại để Bước 5 không thấy)
    hold = quickcheck.pick_holdout(events, by_sid, chosen, st["quickcheck_n"])
    hold_sessions = {e["session_id"] for e in hold}
    # Bước 5
    rv = review.load(cfg)
    syn = synthesize.run(cfg, llm, sessions, events, moves, d, chosen, hold_sessions, rv,
                         holdout_events={e['event_id'] for e in hold})
    # Bước 6
    from .package.skill import capsule_text
    q = quickcheck.run(cfg, llm, sessions, hold, lambda dom: capsule_text(cfg, syn, rv, dom))
    rep = report(cfg, d, chosen, sel, events, moves, syn, q)
    (work_dir(cfg) / "build_report.md").write_text(rep, encoding="utf-8")
    cfg.path("reports").mkdir(parents=True, exist_ok=True)
    (cfg.path("reports") / f"lite_build_{st['slug']}.md").write_text(rep, encoding="utf-8")
    return rep


def _tbl(c: Counter, total: int) -> list[str]:
    L = ["| Giá trị | Số | Tỉ lệ |", "|---|---|---|"]
    for k, v in c.most_common():
        L.append(f"| {k} | {v} | {v / max(total, 1):.0%} |")
    return L


def report(cfg, d, chosen, sel, events, moves, syn, q) -> str:
    names = {g["slug"]: g["name"] for g in d["domains"]}
    stats = (work_dir(cfg) / "mine_stats.json")
    import json
    ms = json.loads(stats.read_text(encoding="utf-8")) if stats.exists() else {}
    L = ["# Expert Capsule, chế độ Lite: báo cáo build", "",
         f"Lĩnh vực đã chọn: {', '.join(names[c] for c in chosen)}.", "",
         "## Bước 3: lọc tín hiệu", "",
         f"- Chọn {len(sel)} lượt ({Counter(s['why'] for s in sel)['random']} ngẫu nhiên).", ""]
    L += _tbl(Counter(names[s["domain"]] for s in sel), len(sel))
    L += ["", "## Bước 4: khai thác", "",
          f"- Gán nhãn được {ms.get('labeled', '?')} / {ms.get('selected', '?')} lượt, loại {ms.get('dropped_invalid', 0)} "
          f"vì trích dẫn sai. Event (khác none): {len(events)}.",
          f"- Phiên gán move cho playbook: {len(moves)}.", "", "Loại phản hồi:", ""]
    L += _tbl(Counter(e["type"] for e in events), len(events))
    L += ["", "Mức riêng:", ""]
    L += _tbl(Counter(e["level"] for e in events), len(events))
    L += ["", "## Bước 5: tổng hợp luật", "",
          "| Lĩnh vực | Event dùng | Luật (đủ bằng chứng) | Ứng viên | Tình huống | Playbook | Mâu thuẫn |",
          "|---|---|---|---|---|---|---|"]
    for slug, x in syn["domains"].items():
        L.append(f"| {x['name']}{' (mỏng)' if x['thin'] else ''} | {x['n_events']} | {len(x['rules'])} | "
                 f"{len(x['candidates'])} | {len(x['cases'])} | {len(x['playbooks'])} | {len(x['conflicts'])} |")
    L += ["", f"- Lõi chung: {len(syn['core'])} luật. Văn phong: {len(syn['style'])} mục.",
          f"- Lượt giữ lại cho Bước 6 (không dùng tổng hợp): {len(syn.get('holdout_events', []))}, "
          f"từ {len(syn['holdout_sessions'])} phiên mới nhất.", "",
          "## Bước 6: kiểm tra nhanh", "", f"**{quickcheck.headline(q)}**", "",
          f"Hệ và judge đều là `{q['models']['systems']}` (cùng họ): con số chỉ để tham khảo, nhỏ và nhiễu.", "",
          "## Việc kế tiếp", "", "1. `capsule review`: duyệt từng luật (giữ, sửa, xoá) và trả lời câu hỏi mâu thuẫn.",
          "2. `capsule package`: sinh capsule vào `expert/`."]
    return "\n".join(L) + "\n"
