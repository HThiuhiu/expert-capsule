# Expert Capsule

**Chưng cất lịch sử chat của bạn với AI (ChatGPT, Claude, Gemini) thành một Agent Skill: AI đọc nó và làm việc theo
tiêu chuẩn, văn phong và cách làm của bạn.**

> *English summary: Expert Capsule turns your own ChatGPT / Claude / Gemini chat history into an
> [Agent Skill](https://agentskills.io/specification) folder (`SKILL.md` + per-domain reference files) that makes an AI
> work by your standards and style. It learns from behaviour, not self-description: the moments you corrected, rejected,
> challenged or accepted an AI answer. Every rule points back to at least two verbatim quotes from two different
> sessions, which stay in a private folder. The CLI and generated capsules are currently in Vietnamese.*

Tín hiệu mạnh nhất về cách bạn làm việc là những lúc bạn **sửa, bác, hỏi vặn hoặc chấp nhận** câu trả lời của AI.
Expert Capsule tìm những lúc đó trong lịch sử chat, gom chúng thành luật dạng "Khi X, làm Y, vì Z", mỗi luật có ít
nhất 2 bằng chứng từ 2 phiên khác nhau, rồi đóng gói thành một thư mục bạn cài được vào Claude Code, Claude.ai,
ChatGPT/Claude Projects, custom instructions hoặc system prompt.

```
expert-<tên>/
  SKILL.md                     # lõi luôn bật: luật chung, văn phong, ba chế độ làm việc (< 5.000 token)
  references/domains/<lv>.md   # theo lĩnh vực: luật có mã (KT-07), tình huống, playbook, câu hỏi mở
  references/style.md          # sổ tay văn phong: mệnh lệnh + ví dụ nguyên văn
  references/exemplars.md      # câu trả lời mẫu đạt chuẩn (viết mới)
  exports/                     # custom_instructions.txt, project_instructions.md, system_prompt.md, HUONG_DAN_CAI.md
  capsule.json                 # phiên bản, số liệu, kết quả kiểm tra nhanh
  private/                     # KHÔNG chia sẻ: đoạn trích bằng chứng, event, lịch sử chỉnh sửa
```

Xem một capsule mẫu (dữ liệu tổng hợp, nhân vật hư cấu): [examples/expert-demo/](examples/expert-demo/).

## Cách hoạt động (chế độ Lite)

| Bước | Việc | Gọi LLM |
|---|---|---|
| 1. Ingest | Đọc export, chuẩn hoá phiên, giữ nhánh sửa prompt và regenerate, **che API key, mật khẩu, email, số điện thoại** | Không |
| 2. Lĩnh vực | Gán lĩnh vực cho từng phiên, gộp nhãn gần nghĩa, đề xuất danh sách để bạn chọn | Rẻ |
| 3. Lọc tín hiệu | Chấm điểm mọi lượt (nhánh regenerate, từ khoá sửa sai, lặp lại yêu cầu, mệnh lệnh ngắn sau câu trả lời dài, lời khen cụ thể), chọn 200 đến 400 lượt | Không |
| 4. Khai thác | Với mỗi lượt: loại phản hồi, khía cạnh bị nhắm, mức riêng (ai cũng sửa / chuẩn ngành / gu riêng), **đoạn trích nguyên văn** (không khớp chuỗi con thì loại) | Rẻ |
| 5. Tổng hợp | Luật theo lĩnh vực, tình huống, playbook (khi đủ 6 phiên), mâu thuẫn, lõi chung, văn phong. Code loại luật dưới 2 event hoặc chỉ từ 1 phiên | Mạnh |
| 6. Kiểm tra nhanh | Trên 15 lần bạn từng sửa AI (giữ lại, không dùng để học): AI có capsule đoán trúng bao nhiêu lời chê của bạn so với AI không có capsule | Mạnh |
| 7. Duyệt | Bạn giữ, sửa câu chữ, sửa phạm vi hoặc xoá từng luật; trả lời các câu hỏi mâu thuẫn | Không |
| 8. Đóng gói | Sinh SKILL.md, file lĩnh vực, mọi bản xuất từ cùng một nguồn; lưu bản cũ để rollback | Không |

Mọi kết quả LLM được cache trên đĩa: chạy lại, đổi lĩnh vực hay thêm lượt chỉ tốn cho phần mới.

## Cài đặt

Cần Python 3.11 trở lên.

```bash
git clone https://github.com/HThiuhiu/expert-capsule.git && cd expert-capsule
pip install -e ".[anthropic]"          # thêm ,embed nếu muốn đặc trưng "lặp lại yêu cầu" (Bước 3)
cp config.local.example.yaml config.local.yaml   # điền tên bạn, chọn cách chạy model
```

## Bắt đầu nhanh

1. **Xuất lịch sử chat** và đặt file vào `data/raw/` (chi tiết: [data/README.md](data/README.md)):
   - ChatGPT: Settings > Data controls > Export data. Tải file zip trong email.
   - Claude: Settings > Privacy > Export data. Tải file zip trong email.
   - Gemini hoặc nguồn khác: chép ra file `.txt`, mỗi lượt mở đầu bằng `User:` hoặc `Gemini:`.
2. **Đặt API key**: `export ANTHROPIC_API_KEY=...` (hoặc `ant auth login`). Không có key: xem mục kế tiếp.
3. **Chạy**:

```bash
capsule ingest                     # Bước 1: xem số phiên và báo cáo reports/step0_data.md
capsule domains                    # Bước 2: in danh sách lĩnh vực
capsule build --domains a,b,c      # Bước 3 đến 6: chọn 2 đến 4 lĩnh vực bạn muốn
capsule review                     # Bước 7: duyệt từng luật
capsule package                    # Bước 8: ra expert/expert-<slug>/
capsule install --target zip       # gói zip để tải lên Claude.ai
capsule demo "một câu hỏi thử"     # so câu trả lời có và không có capsule
```

**Chi phí (ước lượng thô)**: một lần chạy Lite đọc khoảng 2 triệu token, phần lớn ở model rẻ. Với cấu hình mặc định
(Haiku cho Bước 2 và 4, Opus cho Bước 5 và 6) cỡ vài USD; đặt mọi vai là Haiku thì dưới 1 USD. Bảng giá ở
`config.yaml: pricing`.

## Không có API key: chạy trong Claude Code

Mỗi lệnh gọi LLM có thể do **subagent Haiku của Claude Code** trả lời thay cho API:

1. Trong `config.local.yaml`, đặt ba vai `cheap`, `strong`, `judge` là `agent/claude-haiku` (khối C trong file mẫu).
2. Mở Claude Code trong thư mục repo và nói: *"chưng cất lịch sử chat của tôi bằng capsule"*. Skill dự án
   [.claude/skills/capsule-agent-mode](.claude/skills/capsule-agent-mode/SKILL.md) hướng dẫn Claude chạy vòng:
   lệnh dừng khi cần LLM, `capsule queue bundle` gom yêu cầu thành gói, mỗi gói một subagent Haiku trả lời,
   `capsule queue import`, rồi chạy lại lệnh.

Các gói không trộn nhau: ở Bước 6, AI không có capsule và judge không bao giờ nhìn thấy capsule.

## Muốn lịch sử chat không rời máy

Bước 2 và 4 đọc nhiều nội dung chat nhất. Chạy chúng bằng model trên máy qua [Ollama](https://ollama.com):

```yaml
# config.local.yaml
models:
  cheap: {model: "ollama/qwen3:14b"}    # model nào cũng được, miễn trả JSON tốt
```

Bước 5 đọc các event đã rút gọn (trích dẫn ngắn và tóm tắt) cùng khoảng 50 tin nhắn ngắn của bạn để học văn phong;
Bước 6 đọc 15 cặp câu hỏi và câu trả lời AI đã cắt gọn. Muốn không gửi gì lên API thì đặt cả `strong` và `judge` là
`ollama/...`; chất lượng luật khi đó phụ thuộc model bạn chọn.

## Đưa capsule vào AI

| Nơi | Cách làm |
|---|---|
| **Claude Code** | `capsule install --target claude-code` (chép vào `~/.claude/skills/`). Claude tự dùng khi câu hỏi khớp, hoặc gõ `/expert-<slug>` |
| **Claude.ai** | `capsule install --target zip`, rồi Settings > Capabilities > Skills > Upload skill |
| **Claude Projects, ChatGPT Projects, Gemini Gems** | Dán `exports/project_instructions.md` vào ô hướng dẫn; tải `references/domains/*.md` lên làm tài liệu |
| **ChatGPT custom instructions** | Dán `exports/custom_instructions.txt` (nén còn ≤ 1.500 ký tự, giữ luật nhiều bằng chứng và gu riêng trước) |
| **API** | `exports/system_prompt.md` làm system prompt |

Tên mục trong giao diện các hãng có thể đổi theo phiên bản. Mỗi capsule có sẵn hướng dẫn chi tiết ở
`exports/HUONG_DAN_CAI.md`.

## Quyền riêng tư

- Che bí mật và PII bằng regex **ngay lúc ingest**, trước mọi lệnh gọi LLM.
- Dữ liệu ở lại máy bạn: `data/`, `.cache/`, `expert/`, `reports/` và `config.local.yaml` đều nằm trong `.gitignore`.
- Luật và tình huống viết bằng ngôn ngữ chung. Đoạn trích nguyên văn chỉ nằm trong `private/`.
  `capsule package` gắn cờ nếu một đoạn trích dài lọt ra ngoài (`private/redact_flags.json`).
- `capsule install` không bao giờ đưa `private/` vào gói zip hay thư mục skills.
- Ví dụ văn phong trong `SKILL.md` là câu ngắn nguyên văn của bạn. Đọc lại trước khi chia sẻ capsule cho người khác.

## Cấu hình

- `config.yaml`: mặc định chung (model theo vai, ngưỡng, bảng giá).
- `config.local.yaml`: cấu hình riêng của bạn, gộp đè lên `config.yaml`. Mẫu: `config.local.example.yaml`.
- Model theo vai, dạng `provider/model`: `anthropic/...` (SDK chính thức), `openai/...` (mọi API tương thích OpenAI,
  đặt `OPENAI_BASE_URL`), `ollama/...`, `agent/...` (subagent Claude Code).
- **Lĩnh vực tuỳ chỉnh** (`capsule.custom_domains`): cắt phiên theo kiểu việc thay vì theo ngành, ví dụ "phong cách
  nghiên cứu" = mọi phiên review paper, lên kế hoạch dự án, tìm tài liệu. Xem ví dụ trong `config.yaml`.
- **Nhiều capsule**: `capsule --slug <tên> build ...`. Mỗi slug có dữ liệu và thư mục ra riêng, dùng chung nhãn đã có.

## Giới hạn hiện tại

- **Chưa được đánh giá đầy đủ.** Kiểm tra nhanh ở Bước 6 chỉ có 15 lượt, nhiễu, và judge thường cùng họ với hệ được
  chấm. Trên dữ liệu thử đầu tiên, nó chưa cho thấy capsule thắng AI không có capsule; bộ đánh giá đầy đủ (so với
  prompt tự viết, với truy xuất hội thoại thô, Lite so với Deep) chưa làm. Hãy dùng `capsule demo` và tự đánh giá.
- Cần đủ dữ liệu: lĩnh vực dưới 15 phiên bị đánh dấu "mỏng"; playbook chỉ có khi đủ 6 phiên cùng một kiểu việc.
- Nhiều lần sửa AI là kiểu "ai cũng sửa" (code lỗi, sai sự thật) và không tạo luật riêng; phần mang gu cá nhân có thể ít.
- Giao diện dòng lệnh và capsule sinh ra hiện bằng tiếng Việt.
- Chưa làm: học dần khi dùng (`capsule update`), rà soát trước khi chia sẻ (`capsule share`), giao diện web.

## Cấu trúc repo

```
src/capsule/       chế độ Lite: domains, prefilter, mine, synthesize, quickcheck, review, package/, install, agentq
src/pc/            dùng chung (ingest, che PII, gọi LLM, embedding) và chế độ Deep: nhãn mọi lượt, verifier, gold, eval
tests/             pytest, gồm test chạy trọn quy trình với model giả
examples/          capsule mẫu tổng hợp và script sinh nó
vendor/distilly/   prompt và công cụ đóng gói từ distilly (MIT), dùng ở chế độ Deep
.claude/skills/    skill cho Claude Code để chạy bằng subagent
```

Chế độ Deep (`pc ingest | mine | gold | induce | pack`) gán nhãn mọi lượt và thêm pass kiểm chứng bằng model mạnh,
dùng để nghiên cứu và để so với Lite.

## Phát triển

```bash
pip install -e ".[dev]"
python -m pytest -q
```

## Ghi công

- [distilly](https://github.com/titanwings/distilly) (MIT): ý tưởng cổng độc quyền, chỉ thêm không ghi đè, phiên bản
  và rollback, đóng gói thành Agent Skill.
- [Agent Skills specification](https://agentskills.io/specification).
- Nghiên cứu về phản hồi tự nhiên trong hội thoại (arXiv 2407.10944, 2408.15549) và suy ra sở thích từ lần sửa (CIPHER,
  arXiv 2404.15269).

## Giấy phép

MIT. Xem [LICENSE](LICENSE).
