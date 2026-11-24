# data/

Mọi thứ trong thư mục này là dữ liệu riêng và đã nằm trong `.gitignore` (trừ file này).

Đặt file export vào `data/raw/`, mỗi nguồn một thư mục con tuỳ ý:

| Nguồn | Cách lấy | Đặt gì vào `data/raw/` |
|---|---|---|
| ChatGPT | Settings > Data controls > Export data, tải file zip trong email | nguyên file `.zip` |
| Claude | Settings > Privacy > Export data, tải file zip trong email | nguyên file `.zip` |
| Gemini hoặc nguồn khác | Chép hội thoại ra file `.txt`/`.md`, mỗi lượt mở đầu bằng `User:` hoặc `Gemini:` ở đầu dòng; nhiều hội thoại thì ngăn bằng dòng `=== tiêu đề ===` | file `.txt`/`.md` |

Sau `capsule ingest`, các thư mục khác được tạo ra:

- `interim/`: phiên đã chuẩn hoá và đã che API key, mật khẩu, email, số điện thoại.
- `lite/`: dữ liệu trung gian của chế độ Lite (nhãn lĩnh vực, event, luật, kết quả duyệt).
