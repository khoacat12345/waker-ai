# Phase 3 — Báo cáo nghiệm thu

**Dự án:** waker-ai
**Repo:** `C:\Users\tuank\waker-ai` → `https://github.com/khoacat12345/waker-ai`
**Commit Phase 3:** `befe904`
**Thời điểm:** 2026-11-07
**Trạng thái:** ✅ HOÀN TẤT — `pytest tests/` exit code **0**
**Cam kết:** Đã DỪNG sau Phase 3, chưa làm Launch v1.0.

---

## 1. Kết quả kiểm thử

```bash
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe -m pytest tests/
```

```
108 passed, 1 skipped in 60.27s
EXIT CODE = 0
```

| Thông số | Giá trị |
|---|---|
| Automated tests | **108 passed** |
| Skipped | 1 (`test_live_opencode`, bật bằng `WAKER_LIVE_TEST=1`) |
| Failed | 0 |
| Exit code | **0** |
| Python | 3.12.10 |
| Quy mô | `src/` 4.652 dòng · `tests/` 1.702 dòng · 27 module |

---

## 2. Phạm vi đã giao

| Yêu cầu Phase 3 | Trạng thái | File |
|---|---|---|
| Claude Code T1 (`-p --resume`, stream-json) | ✅ code + unit test | `adapters/claude.py`, `claude_events.py` |
| Xử lý permission mode | ✅ `--permission-mode`, cảnh báo khi bị deny | `adapters/claude.py` |
| PTY Tier-3 (ConPTY + pyte) | ✅ code + E2E với fake TUI | `adapters/pty.py` |
| Tự nhận diện prompt + gõ phím/Enter | ✅ regex prompt + idle + auto-approve | `adapters/pty.py` |
| `waker doctor` | ✅ env + tier + injector self-test | `doctor.py` |
| Verify scheduling theo scope | ✅ cache theo digest | `scheduler.py`, `engine.py` |
| Dashboard | ✅ static HTML + live loopback | `dashboard.py` |
| Packaging wheel sạch | ✅ build + cài + chạy thử | `pyproject.toml`, `LICENSE` |
| README English + demo 45s | ✅ | `README.md`, `docs/demo-45s.md` |

---

## 3. Bằng chứng từng mục

### 3.1 `waker doctor` (chạy thật trên máy)

```
waker doctor
============================================================
python   : 3.12.10
platform : Windows 11
git      : git version 2.56.0.windows.2
pty      : OK - pywinpty + pyte ready (ConPTY)
shell    : C:\WINDOWS\system32\cmd.exe

adapters
------------------------------------------------------------
OK opencode       tier T1  (opencode v2.0.32)
    run --session <id> --format json (verified v2.0.32)
-- claude         tier -
    -p --resume <id> --output-format stream-json
-- aider          tier -
    --message non-interactive; no session id to resume
-- codex          tier -
    exec mode; resume support depends on version
-- gemini         tier -
    -p non-interactive
OK any-text-cli   tier T3  (pywinpty)
    PTY keystroke injection (ConPTY + pyte)

injector self-test: PASS - marker seen
```

→ Môi trường đúng; T3 injector hoạt động thật (spawn shell → gõ lệnh → đọc lại
marker), **không đụng vào session AI nào, 0 token**.

### 3.2 PTY Tier-3 — E2E với TUI giả

`tests/test_pty_adapter.py` spawn một TUI text-mode thật qua ConPTY, gửi 2 lượt
liên tiếp trong **cùng process**:

```
turn 1: "hello"  → screen có "ECHO:hello" + prompt "PROMPT>"
turn 2: "second" → screen có "ECHO:second"   (context giữ nguyên)
```

Cơ chế: `pywinpty.PtyProcess` → đọc byte → `pyte.Screen` → dò prompt
(`[>❯$#]\s*$`) + screen ổn định `idle_seconds` → gõ prompt + `\r`.
Có auto-approve cho câu hỏi permission (`y\r`) để tránh false freeze.

### 3.3 Verify scheduling

`tests/test_engine.py::test_verify_cache_avoids_rerunning_unchanged_tasks`:

- 2 task, agent lười làm T1 ở kick 0, T2 ở kick 1.
- Kết quả: `calls_t1.txt` = **1 dòng**, `calls_t2.txt` = **1 dòng**.
- T1 không bị chạy lại ở kick 1 vì digest scope không đổi.

`test_full_suite_is_skipped_until_candidate`:

- Full suite **không chạy** ở kick 0 (chưa candidate, agent chưa claim).
- Chạy đúng 1 lần khi candidate DONE (cộng 1 lần baseline lúc prepare).
- `kick-0/result.json` có `"test_skipped": true`.

### 3.4 Dashboard

- `render_html` escape HTML đúng (`<script>` → `&lt;script&gt;`), hiện progress,
  badge DONE/FAIL, cost, evidence.
- `test_live_dashboard_http` mở server loopback thật, `GET /` trả HTML,
  `GET /api/status` trả JSON.
- CLI: `waker dashboard --out dashboard.html` và `waker dashboard --port 47822`.

### 3.5 Packaging

```text
dist/waker_ai-0.3.0-py3-none-any.whl   64.246 bytes
```

Nội dung wheel (kiểm bằng `zipfile`):

```
waker/cli.py, waker/engine.py, waker/adapters/pty.py
waker/skill_templates/opencode/SKILL.md
waker/skill_templates/claude/SKILL.md
waker/skill_templates/gemini/SKILL.md
waker/skill_templates/generic/AGENTS.md
```

Cài vào venv sạch và chạy thật:

```powershell
python -m venv .venv-wheel
.venv-wheel\Scripts\pip install dist\waker_ai-0.3.0-py3-none-any.whl
.venv-wheel\Scripts\waker.exe --version     # → waker 0.3.0
.venv-wheel\Scripts\waker.exe doctor --json # → JSON hợp lệ
waker install-skill --for opencode          # → tạo .opencode/skills/waker/SKILL.md
waker plan --prompt "..."                   # → tasks.yaml hợp lệ
```

Sau kiểm tra, `.venv-wheel` đã được xoá.

### 3.6 Claude adapter

Unit tests (5) chứng minh:

- Parse `system` / `assistant` / `result` từ stream-json.
- Lấy `session_id`, `total_cost_usd`, `usage` tokens, text.
- Phát hiện permission denial.
- Turn đầu **không** có `--resume`; turn sau có `--resume <id>`.
- `--permission-mode acceptEdits` luôn được truyền.

**Không có live E2E**: máy này không cài `claude` CLI. Ghi nhận trung thực;
`doctor` hiển thị `-- claude tier -`.

---

## 4. Thay đổi kiến trúc trong Phase 3

| Thay đổi | Lý do |
|---|---|
| `RunState.agent_session_id` | Claude tự sinh session id; engine phải lưu id thật để `--resume` lượt sau. OpenCode vẫn dùng `ses_waker_<run>` |
| `TurnContext.resume_id` | Adapter quyết định resume bằng id nào, không hardcode |
| `engine._finish` gọi `adapter.close()` | PTY giữ process sống qua nhiều turn; phải đóng khi kết thúc |
| `scheduler.py` + `verify_cache.json` | Chỉ verify task có scope thay đổi; cache theo digest nội dung |
| `full_suite_every` | Tuỳ chọn chạy full suite định kỳ ngoài candidate/claim |
| `make_dashboard_server` | Tách server khỏi `serve_forever` để test được |

---

## 5. Bug / sự cố đã xử lý

| Sự cố | Xử lý |
|---|---|
| PEP 639 báo lỗi vì vừa `license = "MIT"` vừa classifier MIT | Bỏ classifier license; build sạch |
| `wheel` thiếu trong venv → `python -m build` fail | Thêm `wheel` vào extra `dev`, cài trong venv |
| Dashboard khó test vì server nằm trong hàm blocking | Tách `make_dashboard_server` |
| Test daemon timeout 90s một lần dưới tải full-suite (chạy riêng 3/3 pass) | Nâng deadline lên 120s; ghi nhận là flake môi trường, không phải logic |
| Claude cần session id thật | Thêm `agent_session_id` + `resume_id` như trên |

---

## 6. Sai lệch / giới hạn đã biết

1. **PTY chỉ hỗ trợ Windows** (ConPTY). POSIX (`pty`/`pexpect`) chưa làm trong
   v0.3; `doctor` báo rõ T3 unavailable.
2. **Claude chưa có live E2E** vì CLI không có trên máy. Adapter đã sẵn sàng;
   khi cài `claude`, bật `WAKER_LIVE_TEST=1` với test tương tự OpenCode.
3. **Dashboard mặc định dùng meta-refresh 2s**, chưa dùng WebSocket/JS framework.
   Phù hợp mục tiêu "nhìn nhanh", không phải realtime streaming.
4. **Prompt detection của PTY là heuristic** (`[>❯$#]\s*$` + screen ổn định).
   Có thể false-positive nếu output kết thúc bằng `>`. Có thể override
   `prompt_pattern` khi khởi tạo adapter.
5. **`--permission-mode bypassPermissions`** cần cho unattended đầy đủ nhưng nguy
   hiểm; mặc định vẫn là `acceptEdits`.
6. **Daemon/dashboard không có auth**, chỉ bind `127.0.0.1`.
7. **Chưa có CI** (GitHub Actions) — test chạy local.
8. **Build wheel cần setuptools >= 77** (PEP 639) — đã đặt đúng trong
   `pyproject.toml` (`requires = ["setuptools>=77"]`).

> Ghi chú: bản build trên máy dùng setuptools 84, wheel sạch, không cảnh báo
> license.

---

## 7. Tái lập

```powershell
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe -m pytest tests/

# doctor + injector self-test
.venv\Scripts\waker.exe doctor --inject-test

# build wheel
.venv\Scripts\python.exe -m build --wheel --no-isolation
```

---

## 8. Checklist nghiệm thu

- [x] Claude adapter T1 + permission mode + session discovery
- [x] PTY T3 ConPTY + pyte + prompt detection + auto-approve
- [x] `waker doctor` + tier detection + injector self-test
- [x] Verify scheduling theo scope + cache + full suite có điều kiện
- [x] `waker dashboard` static + live
- [x] Wheel sạch, cài được, chạy được từ venv mới
- [x] README English + bảng so sánh + `docs/demo-45s.md`
- [x] 108 automated tests, **exit code 0**
- [x] Báo cáo này
- [x] Push GitHub
- [x] **Dừng — chưa làm Launch v1.0**

---

## 9. Đề xuất Launch v1.0 (chưa làm)

1. Publish PyPI (`twine upload dist/*`) — wheel đã sẵn sàng.
2. GitHub Actions matrix (Windows/Linux, 3.11/3.12) chạy `pytest` + build wheel.
3. Quay video 45s theo `docs/demo-45s.md`, gắn vào README.
4. POSIX PTY (`ptyprocess`) cho T3 trên Linux/macOS.
5. Claude live test + hướng dẫn permission mode trong docs.
6. Auth token tuỳ chọn cho daemon nếu mở ngoài loopback.
