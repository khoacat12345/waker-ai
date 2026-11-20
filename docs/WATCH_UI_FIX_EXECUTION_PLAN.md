# Execution Plan — Watch UI Hotfix (Direction A)

**Status:** READY FOR APPROVAL — chưa sửa code.
**Direction:** A — fix UI trước, giữ version `2.2.0`, chưa tag/publish.
**Baseline:** `main` at `5d2616d`; working tree clean; tag `v2.2.0` chưa tồn tại.
**Scope:** chỉ sửa `waker watch` / `waker watch --window`; không làm E8, không đổi engine/contract.

## Mục tiêu

Sửa hai lỗi UX thật:

1. Run đã `DONE` hoặc không còn `running` làm `waker watch` nháy lên rồi
   tắt; nội dung bị xoá vì `Live(screen=True)` dùng alternate screen.
2. `waker watch --window` có thể đóng ngay hoặc bị marker cũ chặn 1 giờ;
   lần sau không mở lại được.

Không thay đổi semantics của run, không reset evidence, không đổi `v2.2.0`.

## Nguyên tắc thực thi

- Chỉ sửa UI/CLI + test; không sửa `engine.py`, `detector.py`, `planner.py`.
- Mọi thay đổi phải giữ `--mini`, `--no-fx`, non-TTY và 80/120 cột.
- Không dùng raw key read; `--hold` chỉ dùng Enter thường trong terminal.
- Full pytest xanh trước khi build.
- **Không push, không tag, không publish** nếu chưa có lệnh rõ ràng.

---

## A0 — Preflight

**Việc làm:**

1. Xác nhận `git status` sạch và HEAD `5d2616d`.
2. Xác nhận chưa có tag `v2.2.0`:
   ```bash
   git tag --list "v2.2.0"
   git ls-remote --tags origin "v2.2.0"
   ```
3. Xác nhận `dist/waker_ai-2.2.0*` hiện có và `twine check` vẫn PASS.
4. Chụp lại hành vi lỗi:
   - `waker watch --repo C:\Users\tuank\waker-smoke --run b81c627e`
   - `waker watch ... --window`
5. Xác nhận run `b81c627e` là `DONE` và không có phase metadata.

**Gate:** release chưa tag/publish; worktree sạch.

**Ước lượng:** 10 phút.

---

## A1 — Static deck cho run đã kết thúc

**Mục tiêu:** `waker watch` với run `DONE` in deck một lần và để nội dung
nằm lại trên terminal, không nháy/xoá.

**Việc làm:**

1. Trong `src/waker/ui.py`, tách rõ hai nhánh:
   - `status == "running"` → dùng `Live(screen=True)` như hiện tại.
   - `status != "running"` → in `build_cyber_deck(...)` bằng `Console.print`,
     không dùng `screen=True`, rồi return.
2. Sau khi `Live` kết thúc (run chuyển DONE/FAILED/BLOCKED):
   - render lại **final frame tĩnh** sau khi context `Live` đóng.
   - Đảm bảo frame cuối không bị alternate screen xoá.
3. Thêm `hold: bool = False` cho `watch`:
   - `--hold` chỉ chờ Enter khi stdout là TTY.
   - Không dùng raw key read; non-TTY bỏ qua hold.
4. Giữ nguyên:
   - `--mini`: in một dòng rồi exit.
   - `--no-fx`, `NO_COLOR`, SSH fallback.
   - Layout 22/24 dòng.

**Acceptance:**

- `waker watch --run b81c627e` in full deck và giữ nội dung.
- Không thấy màn hình nháy rồi sạch.
- Run đang chạy vẫn cập nhật live.
- `--mini` vẫn là một dòng.

**Files:** `src/waker/ui.py`

**Ước lượng:** 20–30 phút.

---

## A2 — Sửa vòng đời `--window`

**Mục tiêu:** cửa sổ riêng không đóng ngay, không bị marker cũ chặn oan và
có thể mở lại sau khi đóng.

**Việc làm:**

1. `src/waker/cli.py`:
   - thêm `--hold` cho parser `watch`;
   - truyền `hold` vào `watch_run` và `open_watch_window`.
2. `open_watch_window`:
   - thêm `/wait` vào `cmd /c start` để process cha còn sống trong lúc cửa sổ mở;
   - thêm `--hold` vào command con;
   - marker `watch.window` đổi từ timestamp đơn sang JSON:
     ```json
     {"pid": 12345, "started": 1760000000.0}
     ```
   - nếu marker cũ là text hoặc PID đã chết: xoá marker và cho mở lại;
   - nếu PID còn sống: trả `False` để tránh mở trùng;
   - nếu launch lỗi: xoá marker vừa ghi.
3. Giữ tương thích:
   - Windows-only như hiện tại;
   - non-Windows vẫn fallback terminal;
   - direct `waker watch` không cần `--hold`.

**Acceptance:**

- `--window` mở cửa sổ, hiện deck, chờ Enter rồi mới đóng.
- Đóng cửa sổ rồi chạy lại `--window` mở được ngay.
- Khi cửa sổ đang mở, lệnh thứ hai không mở trùng.
- Marker rác từ phiên bản cũ không chặn.

**Files:** `src/waker/ui.py`, `src/waker/cli.py`

**Ước lượng:** 20–30 phút.

---

## A3 — Tests

**Việc làm:**

1. `tests/test_ui.py`:
   - test run `DONE` render static deck (không dùng alternate screen);
   - test `--hold` chỉ hoạt động khi TTY;
   - test marker JSON cũ/không hợp lệ bị bỏ qua;
   - test marker PID còn sống chặn mở trùng;
   - test PID đã chết cho mở lại;
   - test command con có `--hold`.
2. `tests/test_cli.py`:
   - parser `watch --hold`;
   - `--mini` vẫn trả một dòng.
3. Test thủ công:
   - `waker watch --repo C:\Users\tuank\waker-smoke --run b81c627e`
   - `waker watch ... --window` → Enter để đóng, mở lại lần 2.
   - Một run đang chạy (nếu có) vẫn live.

**Gate:** targeted tests xanh; không regression UI.

**Ước lượng:** 20 phút.

---

## A4 — Verification & rebuild v2.2.0

Vì chưa tag/publish, giữ nguyên version `2.2.0`; không bump 2.2.1.

**Việc làm:**

1. Cập nhật `CHANGELOG.md` mục `v2.2.0`:
   - Fixed: completed-run deck stays visible;
   - Fixed: `--window` lifecycle/stale marker.
2. Cập nhật `docs/release-v2.2.0.md` cùng hai mục.
3. Chạy full pytest.
4. Chạy:
   ```bash
   python -m build
   twine check dist/waker_ai-2.2.0*
   ```
5. Kiểm tra `waker --version` = `2.2.0`.
6. Không sửa version trong `pyproject.toml`/`__init__.py`.

**Gate:**

- Full pytest: 0 failed, 1 skipped (live OpenCode opt-in).
- Build wheel + sdist thành công.
- `twine check` 2 artifact PASS.
- Manual `watch` / `--window` đạt acceptance.

**Ước lượng:** 15 phút.

---

## A5 — Release/tag gate (chờ lệnh)

Chỉ thực hiện sau khi user duyệt rõ ràng:

```bash
# sau khi code fix đã commit
git tag -a v2.2.0 -m "waker-ai v2.2.0"
git push origin v2.2.0
# publish chỉ khi có lệnh riêng:
twine upload dist/waker_ai-2.2.0*
```

Không tự chạy tag/push/publish.

## Commit dự kiến

```text
fix(ui): keep completed Cyber-Deck visible and fix watch window lifecycle
```

## Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Alternate screen vẫn xoá frame cuối | test static path + manual DONE run |
| `cmd /wait` khác nhau giữa Windows shells | test PowerShell/Windows; fallback terminal |
| Marker PID bị tái sử dụng | lưu thêm `started`; chỉ dùng PID khi còn sống |
| `--hold` treo pipe/chatbox | chỉ hold khi stdout TTY; non-TTY bỏ qua |
| Sửa UI làm vỡ layout | chạy test 120/80 cột hiện có |

## Tổng thời gian

**Khoảng 1.5–2 giờ**, gồm code, test, build và nghiệm thu thủ công.
Không bao gồm thời gian chờ duyệt push/tag/publish.

**Checkpoint:** chờ lệnh bắt đầu A1.
