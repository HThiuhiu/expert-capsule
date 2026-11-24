# Capsule mẫu: `expert-demo`

**Dữ liệu tổng hợp.** "Minh" là nhân vật hư cấu, một nhà phân tích kinh tế (ví dụ trong thiết kế của dự án). Không
có lịch sử chat thật nào ở đây; các "đoạn trích" trong `private/` cũng là câu viết mẫu.

Dùng để:

- Xem một capsule trông thế nào trước khi chạy trên dữ liệu của bạn: mở `expert-demo/SKILL.md`, rồi
  `references/domains/*.md` (luật có mã, tình huống, playbook, câu hỏi mở).
- Thử cài vào AI: chép thư mục `expert-demo/` (bỏ `private/`) vào thư mục skills của Claude Code, hoặc dán
  `exports/project_instructions.md` vào một Project. Hướng dẫn: `expert-demo/exports/HUONG_DAN_CAI.md`.
- Thấy `private/` chứa gì: `evidence.jsonl` (mỗi luật trỏ về đoạn trích bằng chứng), `events.jsonl`. Với capsule
  thật, thư mục này không bao giờ được chia sẻ.

Sinh lại: `python examples/make_demo.py` (dùng đúng code đóng gói Bước 8).
