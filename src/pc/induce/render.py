"""Đóng gói capsule thành file người và agent đọc được.

- SKILL.md: Agent Skill cho Claude Code (ý từ distilly: profile đóng gói thành Skill). Chỉ chứa quy tắc đã trừu tượng
  hoá, không trích nguyên văn (F5). Đầu file có "Tóm tắt luôn bật" giới hạn ký tự (distilly owner profile_builder).
- ledger.md: sổ học (F5). Mỗi quy tắc trỏ về event và đoạn trích nguyên văn. Chỉ để dùng nội bộ.
- open_questions.md: quy tắc mâu thuẫn chờ bạn quyết (B7, distilly merger.md "để người dùng quyết").
"""
from __future__ import annotations

from collections import defaultdict

_IDIO_ORDER = {"personal": 0, "domain_norm": 1, "universal": 2, None: 3}
_IDIO_VI = {"personal": "riêng", "domain_norm": "chuẩn ngành", "universal": "phổ quát", None: "?"}


def _key(r: dict):
    return (_IDIO_ORDER.get(r.get("idiosyncrasy"), 3), -len(r["support_events"]), -r["n_sessions"], r["rule_id"])


def _line(r: dict) -> str:
    because = f" Vì: {r['because']}" if r.get("because") else ""
    return (f"- **Khi** {r['when']} → {r['do_or_dont']}{because} "
            f"`{r['rule_id']} · {len(r['support_events'])} event/{r['n_sessions']} phiên · {_IDIO_VI.get(r.get('idiosyncrasy'))}`")


def summary(rules: list[dict], max_chars: int = 3000) -> str:
    """Quy tắc supported + riêng, xếp theo độ ủng hộ, cắt cho vừa `max_chars`."""
    pick = sorted((r for r in rules if r["status"] == "supported" and r["exclusive"]), key=_key)
    out: list[str] = []
    size = 0
    for r in pick:
        s = f"- Khi {r['when']} → {r['do_or_dont']}"
        if size + len(s) + 1 > max_chars:
            break
        out.append(s)
        size += len(s) + 1
    return "\n".join(out) if out else "- (Chưa có quy tắc đủ bằng chứng: cần ≥ 3 event từ ≥ 2 phiên.)"


def skill_md(rules: list[dict], name: str, n_events: int, task_types: list[str], max_chars: int = 3000) -> str:
    sup = [r for r in rules if r["status"] == "supported" and r["exclusive"]]
    cand = [r for r in rules if r["status"] == "candidate" and r["exclusive"]]
    conf = [r for r in rules if r["status"] == "conflicted"]
    generic = sum(1 for r in rules if not r["exclusive"] and r["status"] != "superseded")
    L = ["---", f"name: {name}",
         "description: \"Rubric cá nhân học từ lịch sử sửa sai của người dùng. Dùng khi trả lời, phản biện bài, "
         "hoặc tự kiểm câu trả lời trước khi gửi cho người này.\"",
         "---", "", f"# {name}", "",
         "Sinh tự động bởi `pc induce` (B7). Không sửa tay: chạy lại `pc induce` để cập nhật.", "",
         "## Tóm tắt luôn bật", "", summary(rules, max_chars), "",
         "## Cách dùng", "",
         "1. Xác định loại việc (task_type) của yêu cầu.",
         "2. Lấy các quy tắc có `when` khớp ngữ cảnh. Ưu tiên quy tắc `riêng` và có nhiều event.",
         "3. Trả lời. Trước khi gửi, tự kiểm từng quy tắc khớp, sửa chỗ vi phạm.",
         "4. Chế độ phản biện: khi người dùng dán bài, chê theo các quy tắc khớp và nói rõ vì sao.",
         "5. Quy tắc `ứng viên` là bằng chứng mỏng: dùng như gợi ý, không coi là luật.", ""]
    L += ["## Quy tắc đã có bằng chứng", ""]
    if not sup:
        L += ["(Chưa có.)", ""]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in sup:
        groups[(r["task_types"] or ["other"])[0]].append(r)
    for tt in sorted(groups, key=lambda t: (task_types.index(t) if t in task_types else 99, t)):
        L += [f"### {tt}", ""] + [_line(r) for r in sorted(groups[tt], key=_key)] + [""]
    L += ["## Quy tắc ứng viên (bằng chứng mỏng)", ""]
    L += [_line(r) for r in sorted(cand, key=_key)] or ["(Không có.)"]
    L += ["", "## Đang mâu thuẫn, chưa áp dụng", ""]
    L += [_line(r) + f" ↔ {', '.join(r['conflicts'])}" for r in sorted(conf, key=_key)] or ["(Không có.)"]
    missing = [t for t in task_types if t not in {x for r in sup for x in r["task_types"]}]
    L += ["", "## Giới hạn", "",
          f"- Học từ {n_events} correction event thuộc split train. Không suy rộng ra ngoài các loại việc đã thấy.",
          f"- {generic} quy tắc bị loại khỏi file này vì là lời khuyên chung (cổng độc quyền).",
          "- Loại việc chưa có quy tắc đủ bằng chứng: " + (", ".join(missing) if missing else "không có") + ".",
          "- Thiếu bằng chứng thì nói thẳng là không biết người dùng muốn gì, đừng đoán.", ""]
    return "\n".join(L)


def ledger_md(rules: list[dict], cases_by_event: dict[str, dict], titles: dict[str, str]) -> str:
    L = ["# Sổ học (F5)", "",
         "Mọi thứ capsule đã học, mỗi mục trỏ về bằng chứng. File này có trích nguyên văn: chỉ dùng nội bộ.", "",
         "Muốn xoá một mục: thêm `event_id` vào `capsule/exclude.txt` (mỗi dòng một id) rồi chạy lại `pc induce`.",
         "Event bị loại sẽ không được học lại.", ""]
    for r in sorted(rules, key=lambda r: r["rule_id"]):
        L += [f"## {r['rule_id']} · {r['status']}" + ("" if r["exclusive"] else " · chung chung"), "",
              f"- Khi: {r['when']}", f"- {r['do_or_dont']}", f"- Vì: {r.get('because') or '(không rõ)'}",
              f"- task_types: {', '.join(r['task_types'])} · aspects: {', '.join(r['aspects'])} · "
              f"{_IDIO_VI.get(r.get('idiosyncrasy'))}",
              f"- Thấy lần đầu {(r['first_seen'] or '?')[:10]}, lần cuối {(r['last_seen'] or '?')[:10]}"]
        if r["scope_history"]:
            L += [f"- Đã thu hẹp phạm vi {len(r['scope_history'])} lần. Bản gốc: {r['scope_history'][0]['from']}"]
        if r["conflicts"]:
            L += [f"- Mâu thuẫn với: {', '.join(r['conflicts'])}"]
        if r["superseded_by"]:
            L += [f"- Bị thay bởi: {r['superseded_by']}"]
        L += ["", "| event | phiên | lời user (nguyên văn) | AI bị bác ở (nguyên văn) |", "|---|---|---|---|"]
        for eid in r["support_events"]:
            c = cases_by_event.get(eid, {})
            ev_span = (c.get("evidence") or ["", ""])[0]
            cue = c.get("cue_span") or (c.get("evidence") or ["", ""])[1]
            L.append(f"| `{eid}` | {_cell(titles.get(c.get('session_id'), '?'), 40)} | {_cell(ev_span, 160)} | "
                     f"{_cell(cue, 120)} |")
        L.append("")
    return "\n".join(L)


def _cell(s: str, n: int) -> str:
    s = (s or "").replace("|", "\\|").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def questions_md(questions: list[dict], rules_by: dict[str, dict]) -> str:
    L = ["# Câu hỏi mở cho bạn (B7)", "",
         "Hai quy tắc trái nhau, event cách nhau không quá 90 ngày nên chưa biết cái nào đúng.",
         "Trả lời bằng cách ghi quyết định dưới mỗi mục; lần sau Claude sẽ sửa rubric theo đó.", ""]
    if not questions:
        return "\n".join(L + ["(Không có mâu thuẫn.)", ""])
    for i, q in enumerate(questions, 1):
        a, b = rules_by[q["rule_a"]], rules_by[q["rule_b"]]
        L += [f"## {i}. {a['rule_id']} ↔ {b['rule_id']}", "",
              f"- Có sẵn ({a['rule_id']}): khi {a['when']} → {a['do_or_dont']}",
              f"- Mới ({b['rule_id']}, event `{q['event_id']}`): khi {b['when']} → {b['do_or_dont']}",
              f"- Lý do inducer cho là mâu thuẫn: {q.get('reason') or '(không nêu)'}", "",
              "Chọn: giữ cái cũ / theo cái mới / giữ cả hai cho hai tình huống khác nhau (ghi rõ tình huống).",
              "", "Quyết định:", ""]
    return "\n".join(L)
