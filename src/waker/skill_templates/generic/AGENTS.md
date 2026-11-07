## waker supervisor

Khi người dùng nói "dùng waker", "canh việc này", "làm tới cùng":

1. Nếu có run đang chạy: `waker status --format md --repo .` và chèn nguyên bảng.
2. Run mới:
   - `waker plan --prompt "<nguyên văn prompt>" --out .waker/tasks.yaml --repo .`
   - In file + cảnh báo lint, hỏi `OK để chạy?`
   - `waker start --detach --repo . --tasks .waker/tasks.yaml --test "<lệnh test>" --adapter generic --agent "<lệnh agent>"`

3. Không tự tuyên bố task xong. Chỉ `waker status` / `waker report` quyết định.
4. Không sửa `tasks.yaml` hay file test sau khi start.
