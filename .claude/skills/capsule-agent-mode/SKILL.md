---
name: capsule-agent-mode
description: Chạy pipeline Expert Capsule (chưng cất lịch sử chat thành Agent Skill mang phong cách người dùng) ngay trong Claude Code, không cần API key - mọi lệnh gọi LLM do subagent Haiku trả lời qua hàng đợi. Dùng khi người dùng muốn chưng cất lịch sử chat của họ, chạy capsule domains / build / demo với model agent/..., hoặc khi một lệnh capsule báo "yêu cầu chờ subagent".
---

# Chạy Expert Capsule bằng subagent (chế độ agent)

Mỗi lệnh `capsule` khi cần LLM sẽ ghi yêu cầu vào `.cache/agent_queue/` rồi dừng với dòng
`Dừng ở <bước>: N yêu cầu chờ subagent`. Việc của bạn là cho subagent trả lời rồi chạy lại lệnh. Kết quả nằm trong
cache, nên chạy lại không tốn gì cho phần đã xong.

## Chuẩn bị (một lần)

1. `pip install -e ".[dev]"`
2. Nếu chưa có `config.local.yaml`: chép `config.local.example.yaml` thành `config.local.yaml`, điền `owner_name`,
   `slug`, và để ba vai `cheap`, `strong`, `judge` là `agent/claude-haiku`.
3. Người dùng đặt file export vào `data/raw/` (xem `data/README.md`). Không tự đi tìm file export ngoài repo.

## Vòng lặp cho mỗi lệnh

1. Chạy lệnh (ví dụ `capsule domains`).
2. Nếu thấy "yêu cầu chờ subagent": chạy `capsule queue bundle`. Lệnh in ra danh sách file `.cache/agent_bundles/*.md`.
3. Với **mỗi** file gói, mở một subagent riêng, chạy song song: Agent tool, `subagent_type: general-purpose`,
   `model: haiku`, prompt đúng như sau (thay đường dẫn):

   > Read the file <ĐƯỜNG DẪN TUYỆT ĐỐI TỚI GÓI .md> completely (it is long: use offset/limit until the line
   > "=== END OF BUNDLE ===") and follow the instructions in its header exactly. You act as the language model for
   > every request in it: for each request, behave as an assistant whose system prompt is the SYSTEM text (or SHARED
   > BLOCK) of that request, and answer its USER text. Write all answers, as JSON Lines, to the answers file named in
   > the header, with one Write call. The answers file must contain only JSON lines (never the "END OF BUNDLE" line).
   > Verbatim quotes must be copied character-for-character. Do not read any other file, do not run code, do not
   > modify any other file. When finished, reply only with "done <number of lines written>".

4. Chờ **mọi** subagent xong, rồi chạy `capsule queue import`.
5. Chạy lại đúng lệnh ở bước 1. Lặp đến khi lệnh chạy hết mà không còn yêu cầu chờ.

Quy tắc:
- Không tự trả lời các gói thay subagent, không sửa file đáp án. Dòng hỏng thì cứ chạy lại lệnh: yêu cầu sai sẽ được
  hỏi lại một lần kèm lời nhắc.
- Một gói chỉ có một tag (`capsule queue bundle` đã tách sẵn). Ở Bước 6, gói `qc_capsule`, `qc_base` và `qc_judge`
  phải do các subagent khác nhau làm, để hệ không có capsule không nhìn thấy capsule.
- Không chép nội dung chat của người dùng vào câu trả lời của bạn quá mức cần thiết.

## Cả quy trình

| Bước | Lệnh | Ghi chú |
|---|---|---|
| 1 | `capsule ingest` | Không gọi LLM |
| 2 | `capsule domains` | In danh sách lĩnh vực. **Hỏi người dùng** chọn lĩnh vực nào, đừng tự chọn |
| 3-6 | `capsule build --domains a,b` | Nhiều vòng: khai thác, tổng hợp luật, kiểm tra nhanh |
| 7 | `capsule review` | Tương tác: bảo người dùng tự chạy trong terminal của họ |
| 8 | `capsule package` | Ra `expert/expert-<slug>/` |
| | `capsule install --target claude-code` hoặc `--target zip` | Đưa capsule vào AI |
| | `capsule demo "<câu hỏi>"` | So câu trả lời có và không có capsule |

Khi báo kết quả cho người dùng: đọc `reports/lite_build_<slug>.md`, nêu số luật theo lĩnh vực và kết quả kiểm tra
nhanh, kể cả khi capsule thua bản không capsule.

## Không bao giờ

- Commit hay chia sẻ `data/`, `.cache/`, `expert/`, `reports/`, `config.local.yaml`.
- Đưa thư mục `private/` của capsule vào bất kỳ bản xuất hay gói zip nào.
