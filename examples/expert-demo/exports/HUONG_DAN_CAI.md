# Cách đưa capsule `expert-demo` vào AI

Capsule giúp AI làm việc theo tiêu chuẩn và văn phong của Minh. Một capsule, nhiều cách nạp. Đường dẫn trong giao
diện các hãng có thể đổi theo phiên bản; tên mục dưới đây là tên lúc viết.

| Cách | Hợp với | Dùng file |
|---|---|---|
| Agent Skill (khuyến nghị) | Claude Code, Claude.ai, host theo chuẩn Agent Skills | cả thư mục (trừ `private/`) |
| Project | Claude Projects, ChatGPT Projects, Gemini Gems | `exports/project_instructions.md` + file lĩnh vực |
| Custom instructions | ChatGPT thường | `exports/custom_instructions.txt` (≤ 1500 ký tự) |
| System prompt | API, bot | `exports/system_prompt.md` |

## 1. Claude Code
Chép thư mục `expert-demo/` (bỏ `private/`) vào `~/.claude/skills/` (dùng mọi dự án) hoặc `.claude/skills/` của một dự
án. Có repo thì: `capsule install --target claude-code`. Mở phiên mới. Claude tự dùng skill khi câu hỏi khớp mô tả;
gọi thẳng bằng `/expert-demo`.

## 2. Claude.ai (web, desktop)
1. `capsule install --target zip` ra `expert/dist/expert-demo.zip` (đã bỏ `private/`).
2. Settings > Capabilities: bật code execution, rồi mục Skills > Upload skill > chọn file zip.
3. Bật skill. Trong chat mới, hỏi việc thuộc các lĩnh vực của capsule.

## 3. Claude Projects / ChatGPT Projects / Gemini Gems
1. Tạo Project (hoặc Gem) mới.
2. Dán nội dung `exports/project_instructions.md` vào ô hướng dẫn (Instructions).
3. Tải lên làm tài liệu của project:
   - `references/domains/kinh-te-vi-mo.md` (Kinh tế vĩ mô)
   - `references/domains/phan-tich-dau-tu.md` (Phân tích đầu tư)
   - `references/style.md`, `references/exemplars.md`

## 4. ChatGPT custom instructions
Settings > Personalization > Custom instructions: dán `exports/custom_instructions.txt` vào ô mô tả cách ChatGPT nên
trả lời. Bản này chỉ có luật cốt lõi và văn phong, nén còn ≤ 1500 ký tự (gói miễn phí giới hạn 1.500 ký tự, gói
trả phí 5.000 theo findskill.ai, chưa đối chiếu với OpenAI). Đổi `capsule.custom_chars` trong config rồi
`capsule package` để có bản dài hơn.

## 5. API
Dùng `exports/system_prompt.md` làm system prompt (lõi + mọi lĩnh vực). Muốn gọn: ghép thân `SKILL.md` với file lĩnh
vực của câu hỏi.

## Khi AI làm sai trong lúc dùng
Ghi lại: `capsule correct "<cách đúng>" --domain <slug>`. Đủ 5 bản ghi thì cập nhật capsule (giai đoạn 3).

## Không chia sẻ
`private/` chứa đoạn trích nguyên văn từ lịch sử chat. Không tải lên, không gửi cho ai.
