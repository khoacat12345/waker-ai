# Phase 2 — Báo cáo nghiệm thu

**Dự án:** waker-ai
**Repo:** `C:\Users\tuank\waker-ai` → `https://github.com/khoacat12345/waker-ai`
**Thời điểm:** 2026-11-07
**Trạng thái:** ✅ HOÀN TẤT — `pytest tests/` exit code **0**
**Cam kết:** Đã DỪNG sau Phase 2, không sang Phase 3.

---

## 1. Kết quả kiểm thử

```bash
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe -m pytest tests/
```

```
86 passed, 1 skipped in 45.15s
EXIT=0
```

| Thông số | Giá trị |
|---|---|
| Automated tests | **86 passed** |
| Skipped | 1 (`test_live_opencode`, bật bằng `WAKER_LIVE_TEST=1`) |
| Failed | 0 |
| Exit code | **0** |
| Live E2E (chạy riêng) | ✅ passed với OpenCode thật |

**Exit code 0 là điều kiện xuất report này** — đã đạt.

---

## 2. Phạm vi đã giao

| Yêu cầu Phase 2 | Trạng thái | Nơi thực hiện |
|---|---|---|
| OpenCode T1 live qua `--session` | ✅ | `adapters/opencode.py` |
| Đọc stream `--format json` | ✅ | `opencode_events.py` |
| Cost guard (USD) | ✅ | `opencode_events.read_session_usage` + `detector` |
| `waker serve` (background HTTP) | ✅ | `daemon.py` |
| `waker start --detach` | ✅ | `daemon.start_detached` |
| `waker install-skill --for ...` | ✅ | `skill_install.py` + 4 templates |
| Windows Process Tree (`taskkill /T /F` + Job Object) | ✅ | `process.kill_tree`, `winjob.py` |
| Live freeze probe | ✅ | `process.run_live` |
| E2E thực chiến | ✅ | `tests/test_live_opencode.py` + live run bên dưới |

**Quy mô:** `src/` 3.6k dòng · `tests/` 1.2k dòng (ước tính theo file hiện tại).

---

## 3. Bằng chứng E2E với OpenCode thật

### 3.1 Lần chạy đầu — thất bại và tìm ra bug thật

Run `eaa1bb21`:

```
turn 0: exit=1, 114.8s, changed=0, → PARTIAL
turn 1: timeout 240s               → BREAKER
cost: $0.000973
```

Nguyên nhân: prompt chứa lệnh verify kiểu Windows (`C:\...\python.exe -c "..."`).
Adapter cũ chạy qua `shell=True`; `cmd.exe` làm hỏng quoting → OpenCode nhận
prompt méo và thoát 1.

### 3.2 Sửa: chạy bằng argv, không qua shell

- `process.run_live` nhận cả `str` (shell) và `list[str]` (không shell).
- `OpenCodeAdapter` resolve `opencode.exe` thật:
  `WAKER_OPENCODE_BIN` → `shutil.which("opencode.exe")` → npm bin → `opencode`.
- Prompt luôn là **một argv element**; test `test_argv_keeps_prompt_verbatim`
  khoá hành vi này.

### 3.3 Lần chạy thứ hai — phát hiện false TAMPER

Run `b6103c75`: turn 0 kết thúc `TAMPER` vì agent chạy pytest tạo
`tests/__pycache__/*.pyc`, làm hash `tests/**` đổi.

Sửa: `evidence.is_noise()` loại `__pycache__`, `.pytest_cache`, `.mypy_cache`,
`.ruff_cache`, `.pyc/.pyo`, `.venv`, `node_modules` khỏi mọi evidence
(diff, hash, restore). Thêm test `test_hash_globs_ignores_pycache`.

### 3.4 Lần chạy cuối — DONE sạch

Run `cff9c232` (CLI thật, model `opencode-go/deepseek-v4.1-flash`):

```
**waker · run cff9c232 · 1/1 — 100%**
`████████████████`  ⏱ 00:45  🔁 0/1  🧪 —  💰 $0.0016

| ✅ | T1 | tạo file src/live.txt chứa chữ hello | src/live.txt | pass |

Chẩn đoán cuối: DONE
kết luận: DONE (exit 0)
```

| Số liệu | Giá trị |
|---|---|
| Task | 1/1 done, evidence `src/live.txt` |
| Kicks | 0 |
| Thời gian | 45.0s |
| Cost (từ session export) | **$0.001632** |
| Session | `ses_waker_cff9c232` |
| JSON events | có (`text`, `tool_use`, ...) |

→ Chứng minh: session resume thật, JSON stream đọc được, cost lấy được từ
`opencode session export`, gate chấm bằng đĩa.

---

## 4. Cơ chế đã hiện thực

```
                    waker serve (loopback HTTP)
                    /health /status /start /stop /runs
                              │
        ┌─────────────────────┴──────────────────────┐
        │                waker start --detach        │
        │  python -m waker run --run-id <id> ...     │
        │  DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP│
        └─────────────────────┬──────────────────────┘
                              ▼
                    engine loop (per turn)
        ┌───────────────────────────────────────────────┐
        │ OpenCodeAdapter → argv [opencode.exe, run,    │
        │   --session ses_waker_<run>, --auto,          │
        │   --format json, --model ..., <prompt>]       │
        │                                               │
        │ process.run_live:                             │
        │   reader thread → last_activity               │
        │   probe: stdout + repo_activity               │
        │   kill: Job Object + taskkill /T /F           │
        │                                               │
        │ opencode session export (before/after)        │
        │   → cost delta + token delta                  │
        └───────────────────────────────────────────────┘
```

**Cost guard:** `--max-cost` → `Observation.cost_usd ≥ max_cost_usd` → `BREAKER`.
`DONE` được ưu tiên trước guard: run đã xong thật thì không bị giết vì tiền.

**Live freeze probe:** không stdout **và** không file activity trong
`--freeze-after` giây → kill tree, `frozen=True`, turn được chấm `FROZEN`
(không phải chờ hết `--turn-timeout`).

**Windows tree kill:** process được gán vào Job Object với
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; luôn kèm `taskkill /T /F /PID` làm fallback.
Test `test_winjob.py` xác nhận process bị terminate; `test_process.py` xác nhận
freeze/timeout kill hoạt động.

---

## 5. Daemon & Skill

### 5.1 HTTP (chỉ loopback)

| Endpoint | Việc |
|---|---|
| `GET /health` | `{"ok": true}` |
| `GET /status?repo=&run=` | state + ledger JSON |
| `GET /runs?repo=` | danh sách run |
| `POST /start` | spawn detached `waker run` |
| `POST /stop` | kill tree + mark aborted |

Test `test_daemon.py` chạy server thật trên port 0, POST `/start` với fake agent,
poll `/status` tới khi `DONE`, assert 2/2 task done.

### 5.2 Skill

`waker install-skill --for opencode|claude|gemini|generic`:

| Provider | Đích |
|---|---|
| opencode | `.opencode/skills/waker/SKILL.md` |
| claude | `.claude/skills/waker/SKILL.md` |
| gemini | `.gemini/config/skills/waker/SKILL.md` |
| generic | `AGENTS.md` block, idempotent (marker) |

Skill dạy agent: đọc status trước, gửi prompt nguyên văn cho `waker plan`,
không được tự tuyên bố DONE.

---

## 6. Sai lệch / quyết định kỹ thuật

| # | Quyết định | Lý do |
|---|---|---|
| 1 | Cost đọc từ `opencode session export`, không từ `--format json` | Đã kiểm chứng v2.0.32: stream chỉ có `step_start`/`text`/`tool_use`, không có token/cost. `export` có `info.cost` + `info.tokens`. |
| 2 | OpenCode chạy bằng argv + `opencode.exe`, không `shell=True` | Shell làm hỏng prompt có quotes/backslash (run `eaa1bb21` fail thật). |
| 3 | Loại cache khỏi evidence | `__pycache__` gây TAMPER giả (run `b6103c75`). |
| 4 | Daemon dùng `http.server` stdlib | Không thêm dependency; chỉ loopback, phục vụ 1 người dùng. |
| 5 | `start --detach` không cần daemon | Detach là cơ chế của OS; HTTP chỉ là tuỳ chọn cho chatbox. |
| 6 | Skill templates nằm trong `src/waker/skill_templates/` | Cần đóng gói kèm wheel; top-level `skills/` sẽ không được cài. |
| 7 | PTY tier-3 chưa làm | Không nằm trong danh sách Phase 2; để Phase 3. |
| 8 | `waker watch` vẫn chưa có test tự động | Vòng lặp Live vô hạn; `build_rich` được test gián tiếp qua markdown. |

---

## 7. Giới hạn đã biết

1. **Cost theo session**: nếu resume một session đã có từ trước, delta turn đầu
   sẽ tính cả chi phí cũ. Waker luôn tạo session riêng `ses_waker_<run_id>` nên
   trong luồng chuẩn không xảy ra.
2. **Job Object có thể bị từ chối** trong môi trường bị hạn chế (đã có fallback
   `taskkill /T /F`).
3. **Daemon không có auth** — chỉ bind `127.0.0.1`. Chưa phù hợp multi-user.
4. **Verify chạy mọi task mỗi boundary** — chưa schedule theo scope.
5. **Chưa có browser dashboard** và **chưa có Claude live test**.
6. **`waker watch`** chưa có test tự động.

---

## 8. Tái lập trong 3 lệnh

```powershell
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe -m pytest tests/

# live E2E (tốn ~$0.002)
$env:WAKER_LIVE_TEST="1"
$env:WAKER_LIVE_MODEL="opencode-go/deepseek-v4.1-flash"
.venv\Scripts\python.exe -m pytest tests/test_live_opencode.py -q
```

---

## 9. Checklist nghiệm thu

- [x] OpenCode T1 live: `--session`, JSON stream, cost/token
- [x] Cost guard (`--max-cost`) + test
- [x] `waker serve` + `/health /status /start /stop /runs`
- [x] `waker start --detach` + `waker stop`
- [x] `waker install-skill` cho opencode/claude/gemini/generic
- [x] Win32 Job Object + `taskkill /T /F`
- [x] Live freeze probe (không chờ hết timeout)
- [x] E2E thật với OpenCode: run `cff9c232` DONE, $0.001632
- [x] 86 automated tests, exit code 0
- [x] Báo cáo này
- [x] Push lên GitHub
- [x] **Dừng — chờ nghiệm thu Phase 3**

---

## 10. Đề xuất Phase 3 (chưa làm)

1. Adapter PTY tier-3 (ConPTY + pyte) cho agent không có headless.
2. `waker doctor` — probe tier 1/2/3 cho từng CLI.
3. Browser dashboard + lịch sử run.
4. Verify scheduling theo scope + cache kết quả.
5. Claude Code adapter live test.
6. Auth token cho daemon nếu mở ra ngoài loopback.
