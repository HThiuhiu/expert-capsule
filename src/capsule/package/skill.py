"""Sinh SKILL.md (lõi luôn bật) và references/ (file lĩnh vực, style.md, exemplars.md) theo chuẩn Agent Skills.

Viết theo hướng dẫn, không nhập vai. Không chứa đoạn trích bằng chứng (chỉ nằm trong private/), trừ ví dụ văn phong
ngắn theo spec mục 1.1.
"""
from __future__ import annotations

from .. import review
from ..common import settings

MODES = """## Ba chế độ
- Người dùng nhờ làm việc: làm theo luật và playbook.
- Người dùng nhờ phản biện bài của họ: chấm theo luật, mỗi lời chê nói rõ luật nào (mã luật) và vì sao.
- Người dùng hỏi "chuyên gia sẽ làm thế nào": trình bày playbook từng bước."""


def _sent(t: str) -> str:
    t = (t or "").strip()
    return t if not t or t[-1] in ".!?…" else t + "."


def _strip_lead(t: str, word: str) -> str:
    t = (t or "").strip()
    return t[len(word):].lstrip(" ,:") if t.lower().startswith(word.lower() + " ") else t


def _lower_first(t: str) -> str:
    """'Người dùng muốn' -> 'người dùng muốn', giữ chữ viết tắt (AI, BFS)."""
    return t[0].lower() + t[1:] if len(t) > 1 and t[0].isupper() and t[1].islower() else t


def rule_line(r: dict) -> str:
    when = _strip_lead(r.get("when", ""), "Khi").rstrip(".")
    s = f"Khi {_lower_first(when)}: {_sent(r['do'])}" if when else _sent(r["do"])
    because = _strip_lead(r.get("because", ""), "Vì")
    if because.strip(" .()").lower() == "suy luận":  # LLM chỉ ghi nhãn, không có lý do
        because = ""
    if because:
        s += f" Vì {_lower_first(_sent(because))}"
    return s


def domain_list(s: dict) -> list[tuple[str, dict]]:
    return [(slug, x) for slug, x in s["domains"].items() if not x["thin"] and x["rules"]]


def description(owner: str, s: dict) -> str:
    names = ", ".join(x["name"] for _, x in domain_list(s)) or "các lĩnh vực đã chưng cất"
    d = (f"Làm việc theo tiêu chuẩn, văn phong và cách làm của {owner} trong: {names}. Dùng khi người dùng nhờ làm "
         f"việc, nhờ phản biện bài, hoặc hỏi {owner} sẽ làm thế nào trong các lĩnh vực này. Luật học từ những lần "
         f"{owner} sửa, bác, hỏi vặn hoặc chấp nhận câu trả lời của AI.")
    return d[:1020]


def render_skill(cfg, s: dict, version: int) -> str:
    st = settings(cfg)
    owner, name = st["owner_name"], f"expert-{st['slug']}"
    doms = domain_list(s)
    core = s.get("core", [])[: st["max_core_rules"]]
    style = s.get("style", [])[: st["max_style"]]
    L = ["---", f"name: {name}", f"description: {description(owner, s)}", "metadata:",
         f"  capsule_version: \"v{version}\"", f"  domains: \"{', '.join(slug for slug, _ in doms)}\"", "---", "",
         f"# Cách làm việc của {owner}", "", "## Vai trò",
         f"Bạn là trợ lý làm việc theo tiêu chuẩn và phong cách của {owner}. Bạn không phải là {owner}, "
         "và không nói thay họ về những điều họ chưa từng thể hiện.", "",
         "## Luật cốt lõi (áp dụng mọi lĩnh vực)"]
    L += [f"- {r['code']}. {rule_line(r)}" for r in core] or ["- (Chưa có luật xuất hiện ở từ 2 lĩnh vực.)"]
    L += ["", "## Văn phong"]
    L += [f"- {_sent(x['rule'])} Ví dụ: \"{x['example']}\"" for x in style] or ["- (Chưa đủ dữ liệu.)"]
    L += ["", "## Khi gặp câu hỏi thuộc một lĩnh vực", "Đọc file tương ứng trước khi trả lời:"]
    L += [f"- {x['name']}: references/domains/{slug}.md" for slug, x in doms]
    L += ["Câu hỏi ngoài các lĩnh vực trên: chỉ áp dụng luật cốt lõi và văn phong, và nói rõ đây là",
          "vùng chưa có dữ liệu.", "", MODES, "", "## Tham chiếu khác",
          "- Sổ tay văn phong đầy đủ: references/style.md",
          "- Câu trả lời mẫu đạt chuẩn: references/exemplars.md"]
    return "\n".join(L) + "\n"


def render_domain(slug: str, x: dict, max_rules: int = 25, max_cases: int = 8) -> str:
    rules = x["rules"][:max_rules]
    in_core = any(r.get("in_core") for r in rules)
    prefix = (rules or [{"code": "XX-00"}])[0]["code"].split("-")[0]
    L = [f"# {x['name']}", "",
         f"Tiêu chuẩn của lĩnh vực này, học từ {x['n_events']} lần phản hồi. Mã luật dạng {prefix}-07: nhắc mã khi "
         "sửa hoặc khi phản biện.", ""]
    if in_core:
        L += ["Luật có dấu \"→ Rxx\" đã được gộp vào luật cốt lõi trong SKILL.md; ở đây là bản cụ thể cho lĩnh vực này.", ""]
    L += ["## Luật", ""]
    for r in rules:
        L.append(f"- **{r['code']}**{' → ' + r['in_core'] if r.get('in_core') else ''}. {rule_line(r)}")
        extra = []
        if r.get("scope"):
            extra.append(f"Phạm vi: {_sent(r['scope'])}")
        if r.get("exceptions"):
            extra.append(f"Ngoại lệ: {_sent(r['exceptions'])}")
        extra.append(f"Bằng chứng: {len(r['events'])} lần, {len(r['sessions'])} phiên ({r['level']}).")
        L.append("  " + " ".join(extra))
    if not rules:
        L.append("- (Chưa có luật đủ bằng chứng.)")
    if x.get("cases"):
        L += ["", "## Tình huống", ""]
        for i, c in enumerate(x["cases"][:max_cases]):
            L += [f"### T{i + 1}. {c['context'][:90]}",
                  f"- Bối cảnh: {c['context']}", f"- Dấu hiệu: {c['cue']}", f"- Phán đoán: {c['judgment']}",
                  f"- Hành động: {c['action']}"]
            if c.get("exception"):
                L.append(f"- Ngoại lệ: {c['exception']}")
            if c.get("outcome"):
                L.append(f"- Kết cục: {c['outcome']}")
            L.append("")
    if x.get("playbooks"):
        L += ["## Playbook", ""]
        for p in x["playbooks"]:
            L += [f"### {p['name']} ({p['n_sessions']} phiên)"]
            L += [f"{i + 1}. {st}" for i, st in enumerate(p["steps"])]
            if p.get("stop_when"):
                L.append(f"- Dừng khi: {p['stop_when']}")
            if p.get("when_ai_fails"):
                L.append(f"- Khi AI làm hỏng: {p['when_ai_fails']}")
            L.append("")
    L += ["## Câu hỏi mở", ""]
    qs = [c["question"] for c in x.get("conflicts", []) if not c.get("answered")]
    L += [f"- {q}" for q in qs]
    cands = x.get("candidates", [])
    if cands:
        L.append(f"- Dữ liệu chưa đủ: {len(cands)} tiêu chuẩn mới thấy ở một phiên hoặc một lần, chưa thành luật. "
                 "Đừng áp dụng như luật; hỏi lại người dùng khi gặp.")
    if not qs and not cands:
        L.append("- (Không có.)")
    return "\n".join(L).rstrip() + "\n"


def render_style(owner: str, style: list[dict]) -> str:
    L = [f"# Sổ tay văn phong khi làm việc theo tiêu chuẩn của {owner}", "",
         "Mỗi mục là một mệnh lệnh kèm ví dụ nguyên văn từ cách người này viết.", ""]
    L += [f"{i + 1}. {_sent(x['rule'])}\n   Ví dụ: \"{x['example']}\"" for i, x in enumerate(style)] or ["(Chưa đủ dữ liệu.)"]
    return "\n".join(L) + "\n"


def render_exemplars(s: dict, k: int = 10) -> str:
    L = ["# Câu trả lời mẫu đạt chuẩn", "",
         "Câu hỏi và câu trả lời đều được viết mới để minh hoạ luật, không lấy từ lịch sử chat.", ""]
    n = 0
    for slug, x in s["domains"].items():
        for e in x.get("exemplars", []):
            if n >= k:
                break
            n += 1
            L += [f"## {n}. {x['name']}" + (f" (áp dụng {', '.join(e['rules'])})" if e.get("rules") else ""), "",
                  f"**Câu hỏi:** {e['question']}", "", "**Câu trả lời:**", "", e["answer"].strip(), ""]
    if not n:
        L.append("(Chưa có.)")
    return "\n".join(L) + "\n"


def mark_answered(s: dict, rv: dict) -> dict:
    asked = {a["question"] for a in rv.get("answers", [])}
    for x in s["domains"].values():
        for c in x.get("conflicts", []):
            c["answered"] = c["question"] in asked
    return s


def capsule_text(cfg, synth: dict, rv: dict, domain: str) -> str:
    """System prompt của hệ có capsule ở Bước 6: phần thân SKILL.md + file lĩnh vực của câu hỏi (host tự đọc)."""
    s = mark_answered(review.apply(synth, rv), rv)
    body = render_skill(cfg, s, 0).split("---\n", 2)[-1]
    x = s["domains"].get(domain)
    if x and not x["thin"] and x["rules"]:
        body += f"\n\n# Nội dung references/domains/{domain}.md\n\n" + render_domain(domain, x)
    return body
