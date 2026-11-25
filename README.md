# Expert Capsule

**Chưng cất lịch sử chat của bạn với AI (ChatGPT, Claude, Gemini) thành một Agent Skill: AI đọc nó và làm việc theo
tiêu chuẩn, văn phong và cách làm của bạn trong đúng lĩnh vực của bạn.**

> *English summary: Expert Capsule is an [Agent Skill](https://agentskills.io/specification) and Claude Code plugin
> that turns your own ChatGPT / Claude / Gemini chat history into a personal skill folder (`SKILL.md` + per-domain
> rule files + style guide) that makes an AI work by your standards and style. Install it, hand Claude your export,
> and it runs the whole pipeline with subagents (no API key), reviews the rules with you in chat, and installs the
> result. It learns from behaviour, not self-description: the moments you corrected, rejected, challenged or
> accepted an AI answer. Every rule points back to at least two verbatim quotes from two different sessions, which
> stay in a private folder. The CLI and generated capsules are currently in Vietnamese.*

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

## Dùng ngay trong Claude Code (khuyên dùng, không cần API key)

**1. Cài skill** (một lần). Trong Claude Code:

```
/plugin install expert-capsule --marketplace HThiuhiu/expert-capsule
```

Claude Code bản cũ hơn 2.1.275: `/plugin marketplace add HThiuhiu/expert-capsule`, rồi
`/plugin install expert-capsule@expert-capsule`. Không muốn dùng plugin:
`git clone https://github.com/HThiuhiu/expert-capsule ~/.claude/skills/expert-capsule`.

**2. Xuất lịch sử chat** và tải file zip trong email:
- ChatGPT: Settings > Data controls > Export data.
- Claude: Settings > Privacy > Export data.
- Gemini hoặc nguồn khác: chép hội thoại ra file `.txt`, mỗi lượt mở đầu bằng `User:` hoặc `Gemini:`.

**3. Mở Claude Code ở thư mục bất kỳ và nói**, ví dụ:

> Tạo capsule phong cách làm việc của tôi từ lịch sử ChatGPT, file ở ~/Downloads/chatgpt-export.zip

(hoặc gõ `/expert-capsule:expert-capsule`). Claude sẽ:
1. Hỏi tên bạn và AI bạn định dùng capsule.
2. Tạo thư mục làm việc `capsule-workspace/` (đã chặn khỏi git) và đọc file export.
3. Đưa danh sách lĩnh vực trong lịch sử chat để **bạn chọn**.
4. Cho subagent Haiku/Sonnet chạy các bước khai thác và tổng hợp.
5. Cùng bạn **duyệt từng luật ngay trong chat**.
6. Đóng gói và cài capsule (vào Claude Code, file zip cho Claude.ai, hoặc file dán vào ChatGPT).
7. Mời bạn **thử mù A/B**: bạn tự chấm câu trả lời nào giống cách mình làm hơn.

Bị ngắt giữa chừng thì cứ nói "làm tiếp capsule": Claude chạy `capsule status` để biết đang ở bước nào.

Cần Python 3.11+ và PyYAML (`pip install pyyaml`). Subagent tính vào hạn mức (hoặc tiền API) của phiên Claude Code
bạn đang dùng; không cần key riêng.

## Dùng ở nơi khác

| Nơi | Cách cài skill | Ghi chú |
|---|---|---|
| **Claude.ai** | Tải `expert-capsule-skill.zip` ở [Releases](https://github.com/HThiuhiu/expert-capsule/releases/latest), rồi Settings > Capabilities > Skills > Upload skill | Thử nghiệm: Claude.ai không có subagent nên Claude tự trả lời từng gói yêu cầu, chỉ hợp với lịch sử nhỏ |
| **Agent khác đọc Agent Skills** | Giải nén zip vào thư mục skills của agent đó | Có subagent thì chạy như Claude Code, không có thì như Claude.ai |
| **Dòng lệnh, có API key** | Xem mục kế tiếp | Nhanh nhất: gọi model song song |

## Chạy bằng dòng lệnh

Cần Python 3.11 trở lên.

```bash
git clone https://github.com/HThiuhiu/expert-capsule.git && cd expert-capsule
pip install -e ".[anthropic]"          # thêm ,embed nếu muốn đặc trưng "lặp lại yêu cầu" (Bước 3)
capsule init ~/capsule-workspace --owner "Tên bạn" --mode anthropic
cd ~/capsule-workspace                 # hoặc thêm -C ~/capsule-workspace vào mỗi lệnh
```

`--mode` chọn cách chạy model, ghi vào `config.local.yaml` của thư mục làm việc:

| `--mode` | Cần gì | Ghi chú |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` (bash: `export ANTHROPIC_API_KEY=...`; PowerShell: `$env:ANTHROPIC_API_KEY="..."`) | Haiku cho Bước 2 và 4, Opus cho Bước 5 và 6 |
| `haiku` | `ANTHROPIC_API_KEY` | Mọi vai là Haiku, rẻ nhất |
| `openai` | `OPENAI_API_KEY` | Gói ChatGPT Plus/Pro không kèm API key; key tạo ở platform.openai.com, tính tiền riêng |
| `ollama` | [Ollama](https://ollama.com) và một model đã `ollama pull` | Không gửi gì lên API; chất lượng luật phụ thuộc model |
| `agent` | Claude Code | Không gọi API: subagent trả lời qua hàng đợi (skill ở trên tự làm vòng này) |

Rồi chạy:

```bash
capsule ingest ~/Downloads/chatgpt-export.zip   # Bước 1 (hoặc đặt file vào data/raw/ rồi `capsule ingest`)
capsule domains                    # Bước 2: in danh sách lĩnh vực
capsule build --domains a,b,c      # Bước 3 đến 6: chọn 1 đến 4 lĩnh vực bạn muốn
capsule review                     # Bước 7: duyệt từng luật (hoặc --show rồi --keep/--delete/--edit/--answer)
capsule package                    # Bước 8: ra expert/expert-<slug>/
capsule install --target claude-code   # hoặc --target zip cho Claude.ai
capsule demo --blind "một câu hỏi thật của bạn"   # thử mù A/B, rồi capsule demo --reveal A ...
capsule status                     # đang ở bước nào, lệnh kế tiếp
```

**Chi phí (ước lượng thô)**: một lần chạy Lite đọc khoảng 2 triệu token, phần lớn ở model rẻ. Với `--mode anthropic`
cỡ vài USD; `--mode haiku` dưới 1 USD. Bảng giá ở `src/pc/config.default.yaml: pricing`.

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

**Lĩnh vực tuỳ chỉnh** (`capsule.custom_domains` trong `config.local.yaml`): cắt phiên theo kiểu việc thay vì theo
ngành, ví dụ "phong cách nghiên cứu" = mọi phiên review paper, lên kế hoạch dự án, tìm tài liệu. File do
`capsule init` tạo có sẵn ví dụ.

## Muốn lịch sử chat không rời máy

`capsule init --mode ollama` chạy mọi bước bằng model trên máy qua [Ollama](https://ollama.com). Có thể chỉ chạy
Bước 2 và 4 (đọc nhiều nội dung chat nhất) trên máy:

```yaml
# config.local.yaml
models:
  cheap: {model: "ollama/qwen3:14b"}    # model nào cũng được, miễn trả JSON tốt
```

Khi đó Bước 5 vẫn đọc các event đã rút gọn (trích dẫn ngắn và tóm tắt) cùng khoảng 50 tin nhắn ngắn của bạn để học
văn phong, và Bước 6 đọc 15 cặp câu hỏi và câu trả lời AI đã cắt gọn, qua model `strong` và `judge`.

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
- Mọi dữ liệu nằm trong thư mục làm việc của bạn (export, phiên đã chuẩn hoá, cache, capsule, báo cáo). `capsule init`
  ghi `.gitignore` chặn cả thư mục khỏi git. Xoá thư mục là xoá hết.
- Luật và tình huống viết bằng ngôn ngữ chung. Đoạn trích nguyên văn chỉ nằm trong `private/`.
  `capsule package` gắn cờ nếu một đoạn trích dài lọt ra ngoài (`private/redact_flags.json`).
- `capsule install` không bao giờ đưa `private/` vào gói zip hay thư mục skills.
- Ví dụ văn phong trong `SKILL.md` là câu ngắn nguyên văn của bạn. Đọc lại trước khi chia sẻ capsule cho người khác.

## Cấu hình

- Mặc định nằm trong package: `src/pc/config.default.yaml` (model theo vai, ngưỡng, bảng giá).
- `config.local.yaml` trong thư mục làm việc (do `capsule init` tạo) gộp đè lên mặc định. Mẫu đầy đủ:
  `config.local.example.yaml`. Thêm `config.yaml` trong thư mục làm việc cũng được (gộp trước `config.local.yaml`).
- Thư mục làm việc là thư mục hiện tại, hoặc `capsule -C <thư mục> <lệnh>`.
- Model theo vai, dạng `provider/model`: `anthropic/...` (SDK chính thức), `openai/...` (mọi API tương thích OpenAI,
  đặt `OPENAI_BASE_URL`), `ollama/...`, `agent/...` (subagent; `agent/claude-sonnet` gợi ý dùng Sonnet).
- **Nhiều capsule**: `capsule --slug <tên> build ...`. Mỗi slug có dữ liệu và thư mục ra riêng, dùng chung nhãn đã có.

## Giới hạn hiện tại

- **Chưa được đánh giá đầy đủ.** Kiểm tra nhanh ở Bước 6 chỉ có 15 lượt, nhiễu, và judge thường cùng họ với hệ được
  chấm. Trên dữ liệu thử đầu tiên, nó chưa cho thấy capsule thắng AI không có capsule; bộ đánh giá đầy đủ (so với
  prompt tự viết, với truy xuất hội thoại thô, Lite so với Deep) chưa làm. Hãy dùng thử mù
  `capsule demo --blind` và tự đánh giá.
- Cần đủ dữ liệu: lĩnh vực dưới 15 phiên bị đánh dấu "mỏng"; playbook chỉ có khi đủ 6 phiên cùng một kiểu việc.
- Nhiều lần sửa AI là kiểu "ai cũng sửa" (code lỗi, sai sự thật) và không tạo luật riêng; phần mang gu cá nhân có thể ít.
- Giao diện dòng lệnh và capsule sinh ra hiện bằng tiếng Việt.
- Trên Claude.ai (không có subagent) chỉ hợp lịch sử nhỏ, và bỏ kiểm tra nhanh vì không còn chấm mù được.
- Chưa làm: học dần khi dùng (`capsule update`), rà soát trước khi chia sẻ (`capsule share`), giao diện web.

## Cấu trúc repo

Chính repo là một skill (`SKILL.md` ở gốc) kiêm plugin Claude Code (`.claude-plugin/`).

```
SKILL.md           skill điều phối: Claude dẫn bạn từ file export tới capsule đã cài
references/        hướng dẫn chi tiết skill đọc khi cần: xuất lịch sử, vòng subagent, duyệt luật, cài đặt, xử lý lỗi
agents/            subagent capsule-worker (Haiku): trả lời một gói yêu cầu LLM
scripts/           capsule.py (chạy CLI không cần pip install), build_skill_zip.py (gói zip cho Claude.ai)
.claude-plugin/    plugin.json, marketplace.json
src/capsule/       chế độ Lite: workspace, domains, prefilter, mine, synthesize, quickcheck, review, package/, install, agentq
src/pc/            dùng chung (cấu hình, ingest, che PII, gọi LLM, embedding) và chế độ Deep
tests/             pytest, gồm test chạy trọn quy trình với model giả, cả vòng subagent như skill
examples/          capsule mẫu tổng hợp và script sinh nó
vendor/distilly/   prompt và công cụ đóng gói từ distilly (MIT), dùng ở chế độ Deep
```

Chế độ Deep (`pc ingest | mine | gold | induce | pack`) gán nhãn mọi lượt và thêm pass kiểm chứng bằng model mạnh,
dùng để nghiên cứu và để so với Lite. Nó chạy trong thư mục repo (cần `vendor/`).

## Phát triển

```bash
pip install -e ".[dev]"
python -m pytest -q
claude plugin validate .               # kiểm tra manifest plugin, skill và agent
claude --plugin-dir .                  # mở Claude Code với skill từ thư mục này
python scripts/build_skill_zip.py      # ra dist/expert-capsule-skill.zip
```

Phát hành: tăng `version` ở `pyproject.toml`, `src/capsule/__init__.py`, `.claude-plugin/*.json` và `SKILL.md` (test
kiểm tra chúng khớp nhau), rồi đẩy tag `v<version>`. Workflow `release` tự đính kèm file zip vào GitHub Release.

## Ghi công

- [distilly](https://github.com/titanwings/distilly) (MIT): ý tưởng cổng độc quyền, chỉ thêm không ghi đè, phiên bản
  và rollback, đóng gói thành Agent Skill.
- [Agent Skills specification](https://agentskills.io/specification).
- Nghiên cứu về phản hồi tự nhiên trong hội thoại (arXiv 2407.10944, 2408.15549) và suy ra sở thích từ lần sửa (CIPHER,
  arXiv 2404.15269).

## Giấy phép

MIT. Xem [LICENSE](LICENSE).
