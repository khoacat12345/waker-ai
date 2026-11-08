---
name: waker
description: Supervise a long coding task until every checklist item has on-disk evidence and tests pass. Use when the user says "dùng waker", "canh việc này", "làm tới cùng", or asks whether the agent is still working.
---

# waker — supervisor

Bạn **không được** tự tuyên bố task xong. Chỉ daemon quyết định, dựa trên
`git diff ∩ scope` và `verify` exit code.

## Nếu đã có run đang chạy

Mỗi lần user nhắn (kể cả không hỏi tiến độ), trước khi trả lời:

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
  --adapter generic --agent "claude -p --resume {session} {prompt}" \
  [--max-kicks 5] [--max-cost 1.0]
```

5. Trả lời ngay, không im lặng: "Đã bật chạy ngầm. Bạn có thể hỏi mình
   'tiến độ' ngay trong chat, hoặc mở terminal gõ `waker watch --repo .`
   để xem trực tiếp."

## Dừng

`waker stop --repo .`

## Blind evaluation (Kaggle mode)

Khi user nói "chấm mù", "hidden test", "Kaggle mode":

1. Viết hidden tests ra file riêng, **không** đặt trong repo làm việc.
2. `waker vault init --repo .` → lấy `vault_id`.
3. `waker vault add --vault <id> --suite <name> --task T1 <file>`
4. `waker vault validate --vault <id> --repo .` — nếu FAIL, sửa đề rồi chạy lại;
   **không** start khi đề chưa validate.
5. Start: `waker start --detach --vault <id> --tasks .waker/tasks.yaml ...`
6. Khi báo tiến độ: chỉ đọc `hidden x/y` trong `waker status --format md`.
   Không đoán, không in tên test, không in source.
7. **Tuyệt đối** không dán nội dung hidden test vào chat của worker;
   không đưa vault path vào prompt.

## Quy tắc cứng

- Không sửa `tasks.yaml` sau khi start.
- Không sửa file test.
- Không nói "xong" — chỉ đọc `status`/`report`.
- "Còn thiếu gì" = danh sách task `status != done` trong `waker status --format json`.

