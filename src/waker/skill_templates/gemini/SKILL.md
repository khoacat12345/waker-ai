---
name: waker
description: Supervise a long coding task until every checklist item has on-disk evidence and tests pass. Use when the user says "dùng waker", "canh việc này", "làm tới cùng", or asks whether the agent is still working.
---

# waker — supervisor

Bạn **không được** tự tuyên bố task xong. Chỉ daemon quyết định, dựa trên
`git diff ∩ scope` và `verify` exit code.

## Nếu đã có run đang chạy

1. Chạy `waker status --format md --repo .`
2. Chèn **nguyên bảng** vào đầu câu trả lời.
3. Nếu status khác `running`: đọc `waker report --repo .` và tóm tắt đúng số liệu.

## Bắt đầu run mới

1. Lấy **nguyên văn** prompt của user (bỏ tiền tố `@waker` nếu có).
2. `waker plan --prompt "<nguyên văn>" --out .waker/tasks.yaml --repo .`
3. In `.waker/tasks.yaml` + cảnh báo lint, hỏi `OK để chạy? (ok / sửa)`.
4. Khi user đồng ý:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<lệnh test>" \
  --adapter generic --agent "gemini -p {prompt}" \
  [--max-kicks 5] [--max-cost 1.0]
```

5. Trả lời: "Đang chạy ngầm. Gõ 'tiến độ' để xem."

## Dừng

`waker stop --repo .`

## Quy tắc cứng

- Không sửa `tasks.yaml` sau khi start.
- Không sửa file test.
- Không nói "xong" — chỉ đọc `status`/`report`.
- "Còn thiếu gì" = danh sách task `status != done` trong `waker status --format json`.

