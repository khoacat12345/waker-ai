## waker supervisor

Khi người dùng nói "dùng waker", "canh việc này", "làm tới cùng":

1. Nếu có run đang chạy: mỗi lần user nhắn, chạy `waker status --format md --repo .`
   và chèn nguyên bảng trước khi trả lời.
2. Run mới:
   - `waker plan --prompt "<nguyên văn prompt>" --out .waker/tasks.yaml --repo .`
   - In file + cảnh báo lint, hỏi `OK để chạy?`
   - `waker start --detach --repo . --tasks .waker/tasks.yaml --test "<lệnh test>" --adapter generic --agent "<lệnh agent>"`
   - Sau khi start, luôn nhắn: "Đã bật chạy ngầm. Hỏi 'tiến độ' trong chat hoặc
     gõ `waker watch --repo .` để xem trực tiếp."

3. Không tự tuyên bố task xong. Chỉ `waker status` / `waker report` quyết định.
4. Không sửa `tasks.yaml` hay file test sau khi start.
