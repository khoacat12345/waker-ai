---
name: waker
description: Supervise a long coding task until every checklist item has on-disk evidence and tests pass. Use when the user says "dùng waker", "canh việc này", "làm tới cùng", or asks whether the agent is still working.
---

# waker — supervisor

Bạn **không được** tự tuyên bố task xong. Chỉ daemon quyết định, dựa trên
`git diff ∩ scope` và `verify` exit code. Lời của bạn không phải bằng chứng.

## Nếu đã có run đang chạy

1. Chạy `waker status --format md --repo .`
2. Chèn **nguyên bảng** vào đầu câu trả lời.
3. Nếu status là `running`: không suy đoán, không hứa hẹn thay daemon.
4. Nếu status khác `running`: đọc `waker report --repo .` và tóm tắt đúng số liệu
   (task done/total, test, số kick, cost).

## Bắt đầu run mới

1. Lấy **nguyên văn** prompt của user. Không tóm tắt, không diễn giải.
2. `waker plan --prompt "<nguyên văn>" --out .waker/tasks.yaml --repo .`
3. In nguyên `.waker/tasks.yaml` + mọi cảnh báo lint cho user xem.
4. Hỏi đúng một câu: `OK để chạy? (ok / sửa)`.
5. Khi user đồng ý, chạy:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<lệnh test của repo>" \
  --adapter opencode --model <provider/model> [--max-kicks 5] [--max-cost 1.0]
```

Nếu không phải OpenCode, dùng adapter generic:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<lệnh test>" --adapter generic \
  --agent "claude -p --resume {session} {prompt}"
```

6. Trả lời: "Đang chạy ngầm. Gõ 'tiến độ' để xem."

## Dừng

`waker stop --repo .`

## Quy tắc cứng

- Không sửa `tasks.yaml` sau khi đã start (hash sẽ báo TAMPER).
- Không sửa file test. Muốn đổi test thì dừng run, sửa, chạy lại.
- Không nói "xong" — chỉ đọc `status`/`report`.
- Nếu người dùng hỏi "còn thiếu gì", trả lời bằng danh sách task `status != done`
  trong JSON của `waker status --format json`, không tự đoán.
