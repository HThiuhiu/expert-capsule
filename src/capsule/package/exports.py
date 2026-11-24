"""exports/: sinh tự động từ cùng nguồn, không sửa tay. Không bản nào chứa nội dung private/.

Bản càng ngắn thì càng giữ luật có nhiều bằng chứng nhất và nhãn personal, bỏ luật domain_norm trước.
"""
from __future__ import annotations

from .skill import domain_list, render_domain, render_skill, render_style, rule_line


def _body(skill_md: str) -> str:
    return skill_md.split("---\n", 2)[-1].lstrip()


def custom_instructions(owner: str, s: dict, limit: int) -> str:
    """Bản nén cho ô custom instructions: luật cốt lõi và văn phong, thêm luật lĩnh vực nếu còn chỗ."""
    head = (f"Làm việc theo tiêu chuẩn và văn phong của {owner} (không nhập vai {owner}). "
            "Mỗi câu trả lời phải theo các luật sau.")
    items: list[tuple[tuple, str]] = []
    for r in s.get("core", []):
        items.append(((0, r["level"] != "personal", -len(r["events"])), f"- {r['code']}: {rule_line(r)}"))
    for x in s.get("style", []):
        items.append(((1, False, 0), f"- {x['rule'].rstrip('.')}."))
    for slug, x in domain_list(s):
        for r in x["rules"]:
            if r.get("in_core"):
                continue
            items.append(((2 if r["level"] == "personal" else 3, False, -len(r["events"])),
                          f"- [{x['name']}] {r['code']}: {rule_line(r)}"))
    items.sort(key=lambda t: t[0])
    out, n = [head], len(head)
    for _, line in items:
        if n + 1 + len(line) <= limit:
            out.append(line)
            n += 1 + len(line)
    return "\n".join(out) + "\n"


def project_instructions(cfg, s: dict, version: int) -> str:
    body = _body(render_skill(cfg, s, version))
    body = body.replace("Đọc file tương ứng trước khi trả lời:",
                        "Các file lĩnh vực đã được tải lên làm tài liệu của project. Đọc file tương ứng trước khi trả lời:")
    return ("<!-- Dán phần dưới vào hướng dẫn của ChatGPT Project hoặc Claude Project. Tải các file trong "
            "references/domains/ lên làm tài liệu của project. -->\n\n" + body)


def install_guide(name: str, owner: str, s: dict, limit: int) -> str:
    doms = "\n".join(f"   - `references/domains/{slug}.md` ({x['name']})" for slug, x in domain_list(s))
    return f"""# Cách đưa capsule `{name}` vào AI

Capsule giúp AI làm việc theo tiêu chuẩn và văn phong của {owner}. Một capsule, nhiều cách nạp. Đường dẫn trong giao
diện các hãng có thể đổi theo phiên bản; tên mục dưới đây là tên lúc viết.

| Cách | Hợp với | Dùng file |
|---|---|---|
| Agent Skill (khuyến nghị) | Claude Code, Claude.ai, host theo chuẩn Agent Skills | cả thư mục (trừ `private/`) |
| Project | Claude Projects, ChatGPT Projects, Gemini Gems | `exports/project_instructions.md` + file lĩnh vực |
| Custom instructions | ChatGPT thường | `exports/custom_instructions.txt` (≤ {limit} ký tự) |
| System prompt | API, bot | `exports/system_prompt.md` |

## 1. Claude Code
Chép thư mục `{name}/` (bỏ `private/`) vào `~/.claude/skills/` (dùng mọi dự án) hoặc `.claude/skills/` của một dự
án. Có repo thì: `capsule install --target claude-code`. Mở phiên mới. Claude tự dùng skill khi câu hỏi khớp mô tả;
gọi thẳng bằng `/{name}`.

## 2. Claude.ai (web, desktop)
1. `capsule install --target zip` ra `expert/dist/{name}.zip` (đã bỏ `private/`).
2. Settings > Capabilities: bật code execution, rồi mục Skills > Upload skill > chọn file zip.
3. Bật skill. Trong chat mới, hỏi việc thuộc các lĩnh vực của capsule.

## 3. Claude Projects / ChatGPT Projects / Gemini Gems
1. Tạo Project (hoặc Gem) mới.
2. Dán nội dung `exports/project_instructions.md` vào ô hướng dẫn (Instructions).
3. Tải lên làm tài liệu của project:
{doms}
   - `references/style.md`, `references/exemplars.md`

## 4. ChatGPT custom instructions
Settings > Personalization > Custom instructions: dán `exports/custom_instructions.txt` vào ô mô tả cách ChatGPT nên
trả lời. Bản này chỉ có luật cốt lõi và văn phong, nén còn ≤ {limit} ký tự (gói miễn phí giới hạn 1.500 ký tự, gói
trả phí 5.000 theo findskill.ai, chưa đối chiếu với OpenAI). Đổi `capsule.custom_chars` trong config rồi
`capsule package` để có bản dài hơn.

## 5. API
Dùng `exports/system_prompt.md` làm system prompt (lõi + mọi lĩnh vực). Muốn gọn: ghép thân `SKILL.md` với file lĩnh
vực của câu hỏi.

## Khi AI làm sai trong lúc dùng
Ghi lại: `capsule correct "<cách đúng>" --domain <slug>`. Đủ 5 bản ghi thì cập nhật capsule (giai đoạn 3).

## Không chia sẻ
`private/` chứa đoạn trích nguyên văn từ lịch sử chat. Không tải lên, không gửi cho ai.
"""


def system_prompt(cfg, s: dict, version: int, owner: str) -> str:
    parts = [_body(render_skill(cfg, s, version))]
    for slug, x in domain_list(s):
        parts.append(f"# references/domains/{slug}.md\n\n" + render_domain(slug, x))
    parts.append("# references/style.md\n\n" + render_style(owner, s.get("style", [])))
    return ("<!-- System prompt cho API: lõi + mọi file lĩnh vực. Muốn gọn hơn, chỉ ghép file lĩnh vực của câu hỏi. -->\n\n"
            + "\n\n".join(parts))
