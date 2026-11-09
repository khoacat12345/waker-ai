# Problems / backlog

## P-001 — `waker watch` header chưa nhảy `⏱ elapsed` và `💰 cost`

- **Trạng thái:** backlog (ghi ngày 2026-11-09, chưa sửa)
- **Mức độ:** UX / low — không ảnh hưởng logic supervisor
- **Kỳ vọng:** header của `waker watch` hiển thị và cập nhật trực tiếp:

  ```text
  ███████░░░  2/4 · 50%   ⏱ 01:23   🔁 1/5   🧪 PASS   💰 $0.0123
  ```

- **Hiện tại:** `src/waker/ui.py::build_rich` chỉ render progress bar,
  `done/total`, `%`, `kick`, `test`; không có `⏱`/`💰`.
  Bản `waker status --format md` có `⏱` và `💰` (nhưng `💰` bị ẩn khi cost = 0).
- **Yêu cầu:**
  - `⏱` tăng ít nhất mỗi giây khi run `running`; dừng ở `ended_ts` khi run kết thúc.
  - `💰` luôn hiển thị, kể cả `$0.0000`; cập nhật khi `run.json` có cost mới
    (turn/kick), không fake tăng theo giây.
  - `waker watch` vẫn read-only: không ghi `.waker/` mỗi giây, không flicker.
- **Gợi ý implement:**
  - `RunState.elapsed` đã là property tính từ `started_ts` + `time.time()`
    (`src/waker/state.py`), nên chỉ cần render `fmt_duration(state.elapsed)`.
  - Thêm vào header trong `build_rich`:

    ```python
    f"{progress_bar(...)}  {done}/{total} · {percent}%   "
    f"⏱ {fmt_duration(state.elapsed)}   "
    f"🔁 {state.kicks}/{state.max_kicks}   "
    f"🧪 {test_label}   💰 ${state.cost_usd:.4f}"
    ```

  - `watch` reload state mỗi `interval` (mặc định 1s); nếu muốn mượt hơn, có thể
    render elapsed giữa các lần reload, nhưng 1s là đủ.
  - Cân nhắc dùng chung format với `render_markdown` để tránh lệch UI.
- **Cách test:**
  1. Chạy `waker run` với fake agent, mở `waker watch`.
  2. Header phải thấy `⏱ 00:00` và `💰 $0.0000`; sau 1s `⏱` tăng.
  3. Khi agent turn xong, `💰` cập nhật theo cost thật.
- **Acceptance:**
  - [ ] `waker watch` header có `⏱` và `💰`.
  - [ ] `⏱` tăng mỗi giây; dừng khi run kết thúc.
  - [ ] `💰` hiển thị `$0.0000` khi chưa có cost, cập nhật đúng khi cost đổi.
  - [ ] Không ghi file mỗi giây; không flicker.
  - [ ] Test renderer/watch; `pytest` xanh.
- **Files:** `src/waker/ui.py`, `src/waker/state.py`, `tests/`.
