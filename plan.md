# waker-ai — Macro Product & Runtime Spec (v0.1)

> **Slogan:** "Never let your AI coding agent sleep on the job again."
> **Định vị:** Giám sát viên (Watchdog & Supervisor) độc lập cho các AI coding agent CLI.
> **Trạng thái:** Tài liệu thiết kế lịch sử (v0.1). Anti-Slop Phase 0–7 đã hoàn tất trong v2.0.0.
> **Ngày chốt:** 07/11/2026
>
> **Implementation status (2026-11-16):** Phase 0–7 of the Anti-Slop roadmap
> are **[x] COMPLETED** and included in v2.0.0. See
> [`docs/ANTI_SLOP_ROADMAP.md`](docs/ANTI_SLOP_ROADMAP.md).
>
> **Deferred to v2.1 Roadmap:** `test_writer` red→green enforcement,
> `depends_on` enforcement, `fail_to_pass` baseline sets, Phase 6.5 coverage
> audit, notifications, `--yes` contract confirmation, hunk-level revert,
> mutation/coverage adapters, API/async/coupling rules, and multi-repo.
> **Current release:** **v2.2.0** — conditional Grill-Me, timeout profiles,
> phase budget display (see §27). Package built; publish pending approval.
> **Planned v2.2:** Grill-Me contract questions and compact real-time
> CLI/TUI checklist (see §26).
> **Approved next:** conditional Grill-Me + phase selection/timeout profiles
> (see §27).
>
> Anti-Slop phase checklist:
>
> - [x] Phase 0 — contract freeze — COMPLETED
> - [x] Phase 1 — `waker.gate` core + `waker audit` — COMPLETED
> - [x] Phase 2 — test/type/comment guards — COMPLETED
> - [x] Phase 3 — architecture/dead code/dependencies/security + SARIF — COMPLETED
> - [x] Phase 4 — engine enforcement and wake loop — COMPLETED
> - [x] Phase 5 — baseline/rollback/TUI — COMPLETED
> - [x] Phase 6 — v2.0.0 release packaging — COMPLETED
> - [x] Phase 7 — experimental external adapters + basic auto-fix — COMPLETED

---

## 0. TL;DR

Bạn giao 1 prompt lớn cho một AI agent. Agent làm được 40% rồi tự ngắt, hoặc báo "đã xong tất cả" trong khi test đỏ. waker-ai là **process cha** đứng ngoài, canh agent đó:

- Agent xong hết việc → gửi báo cáo, kết thúc.
- Agent làm thiếu → đánh thức, chỉ đích danh task còn thiếu.
- Agent nói láo → đánh thức, kèm log test thật.
- Agent sửa ẩu / sửa test cho xanh → revert + đánh thức.
- Agent đứng máy / lặp vô ích → đổi chiến thuật hoặc báo người.

**Không bao giờ** waker báo "xong" khi evidence trên đĩa chưa xong. Đây là toàn bộ giá trị sản phẩm.

---

## 1. Vấn đề & định vị

### 1.1 Bốn "chứng bệnh" kinh điển

| Bệnh | Biểu hiện thực tế |
|---|---|
| **Premature Exit** | Giao 5 việc, làm 1 việc rồi tự ngắt (exit code 0) |
| **Freeze / Hanging** | Process còn sống nhưng không có output, không có diff trong 5–10 phút |
| **Hallucinated Completion** | In "All tasks completed" trong khi test đỏ |
| **Thrashing Loop** | Sửa đi sửa lại vài dòng, test vẫn fail, fingerprint không đổi |

### 1.2 Định vị

- **Là gì:** supervisor độc lập cho agent CLI (OpenCode, Claude Code, Gemini, Aider, generic process).
- **Không phải:** một model giỏi hơn; không phải orchestrator sở hữu model (đó là việc của swarm).
- **Một câu:** swarm **sản xuất**, waker **canh ca**.

### 1.3 Điều waker KHÔNG làm

- Không tự viết code, không tự viết test.
- Không dùng LLM để phán "đã xong chưa" trong vòng lặp chính.
- Không đảm bảo model dốt thành giỏi — chỉ đảm bảo không báo xanh khi chưa xanh.

---

## 2. Nguyên lý gốc (3 bất biến)

1. **Sự thật đến từ đĩa và exit code**, không đến từ chữ agent in ra.
2. **Mỗi lần đánh thức là một lượt resume đúng session cũ**, không phải gõ phím vào TUI, không phải session mới.
3. **Verify chỉ chạy ở ranh giới turn** (agent đã idle), không chạy giữa lúc nó đang ghi file.

Câu chốt để mọi quyết định thiết kế bám vào:

> **Agent khai — waker kiểm — đĩa phán.**

Hệ quả: trong toàn bộ engine **không có nhánh nào** kiểu `if agent_says_done: exit`. Lời agent chỉ là tín hiệu để soi lại.

---

## 3. Kiến trúc 2 khối

```
┌─ CHATBOX (OpenCode / Claude Code / Gemini / bất kỳ) ─────────────┐
│  user: "dùng waker: làm 4 task A B C D, test phải xanh"          │
│      ↓                                                            │
│  SKILL "waker"  (~60 dòng markdown, KHÔNG chứa logic)            │
│   1. waker plan --prompt "<prompt nguyên văn>" --repo "$PWD"     │
│   2. in tasks.yaml ra chat → user duyệt / sửa / Enter            │
│   3. waker start --detach                                        │
│   4. mỗi lượt trả lời: waker status --format md → chèn đầu câu   │
└───────────────────────────┬───────────────────────────────────────┘
                            │ prompt gốc + tasks.yaml + test command
                            ▼
┌─ WAKER DAEMON (process cha, chạy ngầm, không thuộc chatbox) ─────┐
│  spawn agent → observe → verify → kick → verify → ... → DONE     │
│  ghi .waker/runs/<id>/{run.json,ledger.json,events.jsonl}        │
└───────────────────────────────────────────────────────────────────┘
```

### 3.1 Vì sao phải 2 khối (không gộp thành skill)

- Skill chạy **bên trong** agent → agent chết là skill chết theo.
- Skill không thể là trọng tài cho chính session của nó (tự chấm mình).
- Daemon phải sống ở tầng process cha để còn kill / respawn / resume.

### 3.2 Ranh giới tin cậy

| Việc | Skill được làm | Daemon quyết |
|---|---|---|
| Gửi prompt, start, stop | ✅ | |
| Đọc status để render | ✅ | |
| Sửa `tasks.yaml` sau khi freeze | ❌ | hash check → `TAMPER` |
| Tuyên bố "xong" | ❌ | chỉ từ evidence trên đĩa |

---

## 4. Mô hình dữ liệu trên đĩa

```
.waker/
├── run.json                 # run_id, session_id, repo, config, prompt gốc
├── tasks.yaml               # NGƯỜI sở hữu — freeze, KHÔNG có field status
├── ledger.json              # DAEMON sở hữu — trạng thái derive, agent không ghi được
├── events.jsonl             # append-only audit trail
├── lock                     # chống 2 supervisor cùng repo
├── logs/daemon.log
└── runs/<run_id>/
    ├── run.json
    ├── tasks.frozen.yaml    # bản gốc + hash
    ├── ledger.json
    ├── events.jsonl
    ├── baseline_test.json
    ├── evidence/T1.json ...
    ├── checkpoint.json      # commit hash của từng kick
    ├── kick-N/
    │   ├── prompt.txt       # nguyên văn prompt đã gửi
    │   ├── stdout.log
    │   └── result.json
    └── report.md
```

### 4.1 `tasks.yaml` — hợp đồng, không có status

```yaml
# .waker/tasks.yaml
- id: T1
  desc: "Module Auth"
  scope: ["src/auth/**"]
  verify: "pytest tests/auth -q"
  depends_on: []

- id: T2
  desc: "Module Payment"
  scope: ["src/payment/**"]
  verify: "pytest tests/payment -q"

- id: T3
  desc: "Shipping API"
  scope: ["src/ship/**"]
  verify: "pytest tests/ship -q"

- id: T4
  desc: "API Docs"
  scope: ["docs/api/**"]
  verify: "grep -q '## Authentication' docs/api/README.md"

- id: T0            # tuỳ chọn: giao việc viết test cho agent
  desc: "Viết bộ test cho T1..T3"
  scope: ["tests/**"]
  verify: "pytest tests/ -q"
  test_writer: true  # bật luật red→green (xem §10.2)
```

**Bất biến:** file này **không** có field `status`. Trạng thái là **derived**:

```python
done(T) = (T.scope ∩ changed_files ≠ ∅) and (T.verify.exit_code == 0)
```

Nếu agent sửa `tasks.yaml` → hash mismatch → `TAMPER` → daemon khôi phục bản frozen. (Trên Windows `chmod` gần như vô dụng → dùng hash, không dùng quyền file.)

### 4.2 `ledger.json` — do daemon ghi

```json
{
  "run_id": "7f3a",
  "session_id": "ses_7f3a",
  "kicks": 2,
  "max_kicks": 5,
  "started_at": "2026-11-07T14:00:00+07:00",
  "tasks": {
    "T1": {"status": "done",    "evidence": {"files": ["src/auth/guard.py"], "verify": "pass"}, "since_kick": 0},
    "T2": {"status": "done",    "evidence": {"files": ["src/pay/webhook.py"], "verify": "pass"}, "since_kick": 1},
    "T3": {"status": "failed",  "evidence": {"files": [], "verify": "fail", "reason": "test_ship.py:31 KeyError"}, "since_kick": 2},
    "T4": {"status": "pending", "evidence": null}
  },
  "test": {"exit_code": 1, "failed": ["tests/test_ship.py::test_create"], "signature": "a1b2c3"},
  "fingerprint": "f9e8d7",
  "updated_at": "..."
}
```

### 4.3 `events.jsonl` — append-only, thứ tự bắt buộc

```
{"t":"prepare","baseline_commit":"abc123","tasks_hash":"...","baseline_test":"3 fail"}
{"t":"turn_start","kick":0,"session":"ses_7f3a","cmd":"opencode run ..."}
{"t":"observe","elapsed":42,"diff_hash":"...","changed":["src/auth/guard.py"]}
{"t":"verify","kick":0,"done":["T1"],"pending":["T2","T3","T4"],"test":"fail"}
{"t":"diagnose","kick":0,"label":"PARTIAL"}
{"t":"checkpoint","kick":0,"commit":"def456"}
{"t":"kick_requested","n":1,"prompt_sha":"...","reason":"PARTIAL"}
{"t":"kick_started","n":1,"pid":6236}
{"t":"kick_result","n":1,"exit":0,"diff":"a1b2","test":"fail"}
{"t":"done","kick":2,"report":".waker/runs/7f3a/report.md"}
```

**Luật ghi log:** ghi `kick_requested` **trước** khi spawn, `kick_started` sau khi spawn, `kick_result` sau khi turn kết thúc. Crash giữa chừng vẫn truy được đã gửi gì.

---

## 5. Vòng đời một run

### Phase 0 — Prepare (một lần, trước khi spawn)

```
1. repo_root      = git rev-parse --show-toplevel   (không git → hash+mtime snapshot)
2. baseline_commit = git rev-parse HEAD
3. working tree bẩn → tạo checkpoint commit "waker: baseline"
4. task_list       = đọc --tasks → FREEZE + hash → runs/<id>/tasks.frozen.yaml
5. test_command    = --test | detect() | per-task verify
6. baseline_test   = chạy test 1 lần → {exit, failed_ids[], duration, hash(tests/**)}
7. lock            = .waker/lock {pid, repo, heartbeat_at}
```

**Vì sao cần baseline:** để biết cái gì đỏ sẵn. Nếu repo có 200 test đỏ từ trước, không thể gate "full suite xanh" — phải dùng **fail-to-pass set** (chỉ đòi tập đỏ ban đầu chuyển xanh).

### Phase 0.5 — Decompose + freeze

- Có `--tasks` → dùng luôn, chỉ freeze + hash.
- Có `--prompt` mà không có `--tasks` → gọi **1 lần duy nhất** một model rẻ để bóc prompt thành `tasks.yaml`, in ra cho user xem, `Enter` để chốt (hoặc `--yes` khi chạy đêm).
- Không chốt → **không chạy** (fail closed).

Nguyên tắc: *extract một lần → freeze → verify bằng máy.* Không có chỗ nào cho LLM phán "chắc xong rồi".

### Phase 1 — Start một turn

```bash
opencode run --session <ses_id> --auto --format json \
  --model <provider/model> \
  --title "waker:<run_id>" "<prompt>"
```

- `--format json` → event stream: tool call, file write, token usage (giác quan thứ 2 bên cạnh git).
- `--session` do waker **tự sinh** ngay từ run đầu → truyền y nguyên mọi lần (deterministic nhất).
- **Không** đọc stdin, **không** gửi phím, **không** giữ TUI (trừ adapter T3, xem §9).
- **Phải cho phép truyền `--model`**: default model có thể trỏ vào provider chết (đã gặp `ConnectionRefused` khi test).

### Phase 2 — Observe loop (tick 2s)

```python
Observation(
  turn_state,          # running | idle | exited
  exit_code,
  elapsed,
  last_event_age,      # giây từ event cuối
  last_stdout_age,
  events_count,
  diff_hash,           # hash(sorted path + hash(nội dung)) so với baseline
  changed_files,
  lines_changed,
  in_scope_hits,       # changed_files ∩ task.scope
  agent_claimed_done,  # regex "done|completed|xong|hoàn thành"
)
```

`diff_hash` = `git diff --numstat baseline_commit` mỗi tick, có cache.

### Phase 3 — Verify (chỉ ở ranh giới turn)

Xem §6.

### Phase 4 — Diagnose (decision table)

Xem §7.

### Phase 5 — Act

```
1. checkpoint = git commit "waker: kick-{n}"
2. wake_prompt = build(diagnosis, evidence, history)   # template, xem §8
3. append kick_requested
4. resume đúng session cũ
```

### Phase 6 — Terminate

| Kết cục | Điều kiện | Việc làm |
|---|---|---|
| `SUCCESS` | `DONE` | exit 0, ghi report.md, notify |
| `GAVE_UP` | `BREAKER` | exit 2, notify kèm kick log + fingerprint cuối |
| `BLOCKED` | agent in `BLOCKED:` | exit 3, dừng ngay, không đốt kick |
| `USER_ABORT` | Ctrl-C / `waker stop` | checkpoint, kill process tree, exit 130 |

### Phase 6.5 — Requirement Coverage Audit (trước khi báo DONE)

**Status:** Deferred to v2.1 Roadmap.

```
input : prompt gốc + tasks.frozen.yaml + evidence.json + git diff --stat
hỏi   : "mỗi mệnh đề trong prompt gốc có map tới task nào đã có evidence không?
         liệt kê mệnh đề chưa được phủ"
kết quả: còn mệnh đề chưa phủ → tạo task bổ sung → quay lại vòng lặp
```

Đây là lưới an toàn cho ca **decompose hụt** (yêu cầu bị rơi lúc bóc tách). Audit **không được quyền** nói DONE thay gate — chỉ được quyền phát hiện thiếu và bắt làm tiếp.

---

## 6. Verification gates

Chạy khi `turn_state != running`.

| Gate | Điều kiện pass | Chống được gì |
|---|---|---|
| `G_diff` | `lines_changed > 0` ∧ `in_scope_hits ≠ ∅` ∧ diff không chỉ toàn lockfile/log/.waker | `echo x >> notes.txt` |
| `G_test` | `fail_to_pass ⊆ passed` ∨ (mỗi task có `verify` exit 0) | test đỏ giả xanh |
| `G_tamper` | `hash(tests/**) == baseline_hash` ∧ không có `skip`/`xfail`/`.only` mới | agent sửa test cho xanh |
| `G_task` | mỗi task có ≥1 evidence = (file trong scope + verify xanh) | làm 1/5 rồi báo xong |
| `G_int` | agent không ghi `.waker/**`, không sửa `.git/hooks`, không sửa config waker | agent tự tick xanh |

### 6.1 Chống game — bảng đối chiếu

| Cách agent lười vượt gate | Gate bắt bằng |
|---|---|
| `echo x >> notes.txt` | `in_scope_hits` phải nằm trong `scope` của task |
| Xoá/sửa test để pass | `G_tamper` + revert tests |
| Thêm `pytest.mark.skip` | regex diff trên file test |
| Sửa `tasks.yaml` để `status: done` | file không có status + hash check |
| Viết test rỗng `assert True` | luật red→green cho task `test_writer` (§10.2) |
| Commit rồi revert | diff tính từ baseline, không tính commit count |

---

## 7. Detector — 4 bệnh + decision table

### 7.1 Progress fingerprint (chống đốt kick vô ích)

```python
fp = hash(diff_hash + test_signature + sorted(changed_files))
```

Giống nhau 2 kick liên tiếp = agent đang quay tay → **không tiêu thêm kick**, phải đổi prompt hoặc escalate.

### 7.2 Decision table (thứ tự ưu tiên tuyệt đối)

| # | Nhãn | Điều kiện (AND) | Hành động |
|---|---|---|---|
| 1 | `ALIVE` | turn running ∧ `last_event_age < 120s` | không làm gì |
| 2 | `TAMPER` | `hash(tests)` đổi ∧ fail_to_pass chưa xanh | revert tests → kick "restore tests" |
| 3 | `FROZEN` | turn running ∧ `last_event_age > 300s` ∧ `diff_hash` không đổi | abort turn → checkpoint → kick |
| 4 | `DONE` | `G_test` ∧ `G_task` toàn bộ ∧ `G_int` ∧ audit pass | dừng, báo chuông |
| 5 | `FALSE_DONE` | `agent_claimed_done` ∧ `G_test` đỏ | kick kèm log fail cụ thể |
| 6 | `THRASH` | `fp` giống 2 kick liên tiếp | đổi chiến thuật / escalate |
| 7 | `PARTIAL` | turn ended ∧ một số task chưa done | kick kèm danh sách task thiếu |
| 8 | `STALL` | `fp` không đổi 1 kick ∧ thời gian trôi | kick "bạn không tiến bộ" |
| 9 | `BREAKER` | `kicks ≥ max` ∨ wall-clock ≥ max ∨ cost ≥ max | dừng, notify |

**Vì sao `TAMPER` xếp trên `DONE`:** agent sửa test rồi pass thì trông y hệt thành công. Nếu để `DONE` chạy trước, sản phẩm mất toàn bộ ý nghĩa.

### 7.3 Ba kiểu kết thúc của agent — cùng một cách xử lý

| Agent kết thúc kiểu | Nhãn |
|---|---|
| Thành thật: "em mới xong Task 1" | `PARTIAL` |
| Xạo: "đã xong tất cả!" | `FALSE_DONE` |
| Im lặng chết | `PARTIAL` (gate tự đếm) |

Điểm mạnh: verdict **không đọc lời agent**, nên không phụ thuộc việc nó có thành thật hay không.

---

## 8. Wake engine

### 8.1 Template prompt (deterministic, không để LLM viết)

```python
def build_wake(diag, ledger, tests, cfg):
    missing = [t for t in ledger.pending()]
    fails   = tests.failures[:5]
    return f"""[waker kick {ledger.kicks}/{cfg.max_kicks}] lý do: {diag}

ĐÃ XONG: {', '.join(ledger.done_ids()) or 'chưa có'}
CHƯA XONG: {', '.join(t.id + ' (' + t.desc + ')' for t in missing)}

Test đang đỏ (exit {tests.exit_code}):
{chr(10).join(f'- {f.file}::{f.name} line {f.line}: {f.msg}' for f in fails)}

Việc phải làm ngay: {missing[0].desc} — cần thay đổi trong {missing[0].scope}
Cấm sửa file test. Xong thì chạy: {cfg.test_command}
Nếu bị chặn thật: in đúng 1 dòng BLOCKED: <lý do>"""
```

Mỗi mệnh đề là **một sự thật đọc từ đĩa**: done từ ledger, missing từ tasks.yaml, lỗi từ output pytest thật, lệnh từ config. Không có chỗ để bịa.

Giới hạn prompt: chỉ append **N dòng lỗi cuối** (mặc định 40), dedup theo assert message. Không nhồi log 3000 dòng.

### 8.2 `BLOCKED:` — lối thoát hợp pháp

Cho agent quyền nói "tao bị chặn" thay vì nói dối. Nhận `BLOCKED:` → dừng ngay, notify user, không đốt kick. Không có lối thoát này thì agent chỉ có 2 lựa chọn: lặp vô hạn hoặc bịa.

### 8.3 Session resume — đã kiểm chứng thực nghiệm

```bash
# run 1
opencode run -m opencode-go/deepseek-v4.1-flash --session ses_waker_demo --auto \
  "Ghi nhớ mã này: ZX-4471. Chỉ trả lời đúng 2 chữ: OK"
# → OK

# run 2 (process khác, chạy sau, không có context trong RAM)
opencode run -m opencode-go/deepseek-v4.1-flash --session ses_waker_demo --auto \
  "Mã tôi yêu cầu ghi nhớ là gì? Chỉ trả lời mã đó."
# → ZX-4471

opencode session list
# → ses_waker_demo    Ghi nhớ mã ZX-4471    07/11/2026 14:34:55
```

**Kết luận:** session nằm trên đĩa/server, không nằm trong process. Process chết không mất context. "Gọi lại session cũ" = truyền đúng ID vào lần chạy sau. Không có phép thuật.

Ba cách lấy session id:
1. Waker tự sinh (`ses_<run_id>…`) ngay từ run đầu → truyền y nguyên (deterministic nhất).
2. Parse `session.id` từ `--format json` của run đầu.
3. `opencode session list`.

CLI khác:
- Claude Code: `claude -p --resume <uuid> "<prompt>"`
- Codex/Gemini: kiểm tra bằng `waker doctor`
- Không có session (Aider, chatbox lạ): spawn mới + **context digest** (đã xong gì, thiếu gì, lỗi gì) — mất trí nhớ nhưng evidence trên đĩa bù lại.

---

## 9. Adapter ladder — "mọi agent chatbox trên CLI"

Quan sát dùng chung 100% (git diff, hash, exit code, output, screen buffer). Chỉ khác **kênh đánh thức**.

| Tầng | Cơ chế wake | CLI | Tin cậy |
|---|---|---|---|
| **T1 — Native resume** | `opencode run --session <id>`, `claude -p --resume <id>` | OpenCode, Claude Code, Codex | ⭐⭐⭐⭐⭐ context nguyên vẹn |
| **T2 — Replay context** | Spawn mới + context digest | Mọi CLI có `-p` / `--message` | ⭐⭐⭐⭐ mất trí nhớ, evidence bù |
| **T3 — PTY keystroke** | Spawn trong pseudo-terminal, bơm phím + Enter | **Mọi thứ còn lại**, kể cả chatbox không headless | ⭐⭐⭐ |

### 9.1 Adapter contract

```python
class Adapter(Protocol):
    capabilities: set[str]        # {"headless","session_resume","pty"}
    def start(self, prompt: str, ctx: RunCtx) -> Handle: ...
    def resume(self, handle: Handle, prompt: str) -> Handle: ...
    def probe(self, handle: Handle) -> Observation: ...
    def stop(self, handle: Handle) -> None: ...
```

### 9.2 T3 — PTY chi tiết (Windows)

- Windows: **ConPTY bắt buộc** qua `pywinpty`. Không dùng pipe (TUI không vẽ được, gõ phím không ăn).
- POSIX: `pty` / `pexpect`.
- Parse screen buffer bằng `pyte`.
- Phát hiện "agent đang chờ": screen hash ổn định N giây ∧ không có byte mới ∧ prompt marker regex khớp.
- Gửi prompt: bracketed paste + Enter để tránh nuốt ký tự.

### 9.3 `waker doctor`

```bash
waker doctor -- claude
# T1? có --resume/-p  → tier 1
# T2? có non-interactive mode → tier 2
# T3? PTY mở được, prompt detect được → tier 3
# không gì cả → "không hỗ trợ"
```

Doctor còn tự test injector: gõ marker vô hại, kiểm tra marker xuất hiện trong screen buffer. Có doctor thì tuyên bố "hỗ trợ mọi CLI" mới kiểm chứng được.

---

## 10. Chính sách test

### 10.1 Khi nào chạy test, chạy test nào

| Thời điểm | Chạy gì | Vì sao |
|---|---|---|
| Phase 0 | full suite **1 lần** | biết cái gì đỏ sẵn, không đổ lỗi oan |
| Mỗi turn boundary | `verify` của **task có diff mới** | rẻ, đúng scope (~5–30s) |
| Candidate DONE | full suite + hash tests + coverage audit | đắt, chỉ 1 lần |
| Sau 2 kick fail | full suite + rerun test fail (flaky) | phát hiện hỏng dây chuyền |
| **Không bao giờ** | giữa lúc agent đang ghi file | tránh đỏ giả do file dở dang |

Nguyên tắc: **test rẻ trước, test đắt sau.** Repo lớn chạy full suite mỗi turn = 5 phút → agent bị kick oan vì timeout.

### 10.2 Task viết test (T0) — luật red → green

Nếu chỉ kiểm "test tồn tại và pass", agent sẽ viết `assert True`. Gate của `test_writer: true` là 3 điều:

| Điều kiện | Chống được |
|---|---|
| Test **fail** trên code hiện tại (đỏ) | test không kiểm gì |
| ≥ N assert / không `skip`/`pass` rỗng | test giả |
| Sau khi implement → **pass** (xanh) | đúng nghĩa red→green |

**Status:** Deferred to v2.1 Roadmap.

### 10.3 waker không tự viết test

Ba đường hợp lệ:
1. User đưa `--test "pytest tests/ -q"` (chắc chắn nhất).
2. `waker detect` đọc `pyproject.toml` / `pytest.ini` / `package.json` / `go.mod` → **gợi ý**, user xác nhận.
3. Biến việc viết test thành task `test_writer: true` — agent viết, waker kiểm red→green.

Detect là gợi ý, không phải sự thật: monorepo / repo có nhiều runner phải hỏi user.

---

## 11. Circuit breaker & an toàn

| Cơ chế | Mặc định | Ghi chú |
|---|---|---|
| `max_kicks` | 5 | hết → `GAVE_UP` |
| `max_wall_clock` | 90 phút | |
| `max_cost` | cấu hình | đọc từ event JSON (token usage) |
| `freeze_after` | 300s | đa tín hiệu, không chỉ stdout |
| `alive_threshold` | 120s | dưới ngưỡng này không được coi là freeze |

### 11.1 Windows process tree

`taskkill` không kill con. Agent "đã dừng" có thể vẫn còn subprocess đang ghi file. Phải kill cả tree:

```
taskkill /PID <pid> /T /F
```

hoặc dùng Job Object (`CREATE_NEW_PROCESS_GROUP` + assign job) để OS tự dọn.

### 11.2 Thông báo

**Status:** Deferred to v2.1 Roadmap.

- Windows toast notification
- Beep (tuỳ chọn)
- Telegram (port logic từ `.agents/notify.py`)

### 11.3 Checkpoint / revert

- Commit ở **mỗi ranh giới turn** (`waker: kick-N`), không phải mỗi task (task boundary do máy suy ra, có thể 0.5 task/turn).
- Agent phá code ở kick 3 → `git reset --hard waker: kick-2`.

---

## 12. UI — 3 bề mặt, một nguồn sự thật

**Nguyên tắc:** UI **đọc** `ledger.json`, không bao giờ **tự tính** trạng thái. Nếu không, chat nói 2/4 còn terminal nói 1/4 → mất niềm tin ngay.

| Bề mặt | Khả năng | Dùng khi |
|---|---|---|
| **Chat** (`waker status --format md`) | snapshot + progress bar ASCII, cập nhật mỗi lượt | ngồi trong chatbox |
| **Terminal** (`waker watch`) | Rich Live, spinner, màu, nhấp nháy khi kick | muốn realtime, 1 tab riêng |
| **Browser** (`waker dashboard`) | animation thật, GIF, chart | demo / màn hình phụ |

### 12.1 Trong chat

```
**waker · run 7f3a · 2/4 — 50%**
`████████░░░░░░░░`  ⏱ 12m  🔁 kick 2/5  🧪 FAIL

|   | Task | Bằng chứng | Cổng |
|---|------|-----------|------|
| ✅ | T1 Auth | src/auth/guard.py (+42) | pass |
| ✅ | T2 Payment | src/pay/webhook.py (+88) | pass |
| 🔴 | T3 Shipping | — chưa có diff | fail · test_ship.py:31 |
| ⬜ | T4 API docs | — | chưa chạy |

⚠ kick #2 vừa gửi: "T3 chưa có thay đổi trong src/ship/**. pytest fail: test_ship.py:31 KeyError".
```

### 12.2 Terminal (`waker watch`)

```
╭─ waker ▸ run 7f3a ──────────────────────── 2/4 · 50% ─╮
│  ████████████░░░░░░░░░░  ⠋ đang kiểm tra T3...          │
│  ⏱ 12:41   🔁 2/5   💰 $0.14   🧪 FAIL (1)              │
├────────────────────────────────────────────────────────┤
│  ✅ T1  Auth module          src/auth/**      12s      │
│  ✅ T2  Payment webhook      src/pay/**        8s      │
│  🔴 T3  Shipping API         src/ship/**   ← ĐANG LỖI │
│  ⬜ T4  API docs             docs/api/**               │
├────────────────────────────────────────────────────────┤
│  ▶ opencode · ses_7f3a · turn 00:42                     │
│  ⚠ KICK #2 → "T3 chưa có diff, pytest fail ở dòng 31"  │
╰────────────────────────────────────────────────────────╯
```

Chi tiết tạo cảm giác "có người quản lý": spinner quay, bar mượt, dòng `KICK #n` nhấp nháy đỏ 2 giây mỗi lần đánh thức.

### 12.3 Cột quan trọng nhất: "Bằng chứng"

Thanh 50% mà không nói vì sao thì vô nghĩa. `src/auth/guard.py (+42)` là thứ làm con số đáng tin. Đây là khác biệt giữa "dashboard đẹp" và "dashboard đáng tin".

### 12.4 Tự hiện trong chatbox

Trong `SKILL.md`:

> Nếu `.waker/run.json` tồn tại: **luôn** chạy `waker status --format md` và chèn kết quả vào đầu câu trả lời.

→ Mỗi lần user nhắn bất cứ gì, bảng tiến độ tự xuất hiện, không cần gõ "tiến độ?".

---

## 13. Observability

| Lệnh | Tác dụng |
|---|---|
| `waker status --format md\|json\|rich` | snapshot |
| `waker watch` | TUI sống |
| `waker events --tail 20` | audit trail |
| `waker report` | `report.md` cuối run |
| `waker logs` | daemon log |
| `--dry-run` | in wake prompt mà không gửi |

`report.md` **chỉ là render lại toàn bộ events** → report không bao giờ lệch với thực tế.

---

## 14. CLI surface

```bash
waker plan    --prompt "..." --repo . [--json]     # decompose + freeze, in tasks.yaml
              [--planner rules|llm|swarm] [--review]
waker start   --detach                             # spawn daemon
waker run     --tasks tasks.yaml --test "pytest tests/ -q" --max-kicks 5 \
              -- opencode run --auto "..."         # chạy foreground (không daemon)
waker status  --format md|json|rich
waker watch
waker events  --tail 20
waker report
waker stop
waker detect                                       # gợi ý test command
waker doctor  -- claude                            # probe adapter tier
waker install-skill --for opencode|claude|gemini|generic
waker serve   [--port 47821]                       # local HTTP (cho skill polling)
```

Hai chế độ:
- **Managed** (`waker run`): daemon sở hữu session, mỗi lượt 1 turn.
- **Attach** (`waker watch --session <id>`): quan sát session đang chạy, wake bằng run mới.

---

## 15. Đa nền tảng — skill install

| Provider | Đích cài | Ghi chú |
|---|---|---|
| OpenCode | `.opencode/skills/waker/SKILL.md` | giống `adaptive-swarm-pipeline` đang có |
| Claude Code | `.claude/skills/waker/SKILL.md` (hoặc `.claude/commands/waker.md`) | tuỳ version |
| Gemini CLI | `.gemini/config/skills/waker/SKILL.md` | máy đã có sẵn thư mục này |
| Aider / Codex / chatbox lạ | không có skill system → dùng CLI trực tiếp, hoặc 10 dòng trong `AGENTS.md` | |

Skill chỉ cần 3 lệnh (`plan` / `start` / `status`) → nhân bản gần như free. **Logic không nằm trong skill.**

### 15.1 Nội dung SKILL.md (draft ~40 dòng)

```markdown
---
name: waker
description: Supervise a long coding task until every checklist item has on-disk evidence and tests pass.
---

Khi user nói "dùng waker" / "canh việc này" / "làm tới cùng":

1. Nếu `.waker/run.json` tồn tại → chạy `waker status --format md`, chèn đầu câu trả lời.
2. Nếu chưa có run:
   a. `waker plan --prompt "<prompt nguyên văn của user>" --repo "$PWD" --json`
   b. In bảng tasks.yaml, hỏi user: "OK / sửa gì?" (hoặc dùng --yes nếu user nói chạy luôn)
   c. `waker start --detach`
   d. Trả lời: "Đang chạy ngầm. Gõ 'tiến độ' để xem."
3. Khi user hỏi tiến độ → `waker status --format md` và render nguyên bảng.
4. TUYỆT ĐỐI KHÔNG tự tuyên bố task xong. Chỉ daemon quyết định.
5. Khi user nói dừng → `waker stop`.
```

---

## 16. Cấu trúc repo

```
waker-ai/
├── pyproject.toml              # entrypoint: waker
├── README.md                   # slogan, GIF demo, quickstart
├── plan.md                     # file này
├── SPEC.md                     # (tuỳ chọn) tách riêng runtime spec
├── skills/
│   ├── opencode/SKILL.md
│   ├── claude/SKILL.md
│   ├── gemini/SKILL.md
│   └── generic/AGENTS.md
├── src/waker/
│   ├── cli.py                  # argparse/typer
│   ├── daemon.py               # serve, detach, lock, heartbeat
│   ├── engine.py               # vòng lặp trung tâm
│   ├── state.py                # run ctx, ledger, events (append-only)
│   ├── evidence.py             # task→file map, test signature, tamper check
│   ├── detector.py             # PURE functions: Observation → Diagnosis
│   ├── injector.py             # build_wake() + resume()
│   ├── gates/
│   │   ├── git_gate.py
│   │   └── test_gate.py
│   ├── adapters/
│   │   ├── base.py             # Protocol, capabilities
│   │   ├── opencode.py         # T1
│   │   ├── claude.py           # T1 (v0.2)
│   │   ├── generic_proc.py     # T2
│   │   └── pty_generic.py      # T3 (ConPTY/pyte)
│   ├── detect.py               # test command detection
│   ├── doctor.py
│   ├── notify.py
│   └── ui.py                   # md / rich / dashboard
└── tests/
    ├── fake_lazy.py            # agent giả: làm 1 task rồi báo xong
    ├── fake_liar.py            # agent giả: luôn bảo xong
    ├── fake_tamper.py          # agent giả: sửa test cho xanh
    ├── test_detector.py        # 4 bệnh, pure, không spawn process
    ├── test_gates.py
    ├── test_engine_kick.py     # fake agent → assert kick count + kết cục
    └── test_cli.py
```

**Điểm thiết kế quan trọng:** `detector.py` là **hàm thuần** trên `Observation` → test toàn bộ 4 bệnh mà không cần chạy agent thật, không tốn token.

---

## 17. Roadmap

| Giai đoạn | Nội dung | Thời lượng thực tế |
|---|---|---|
| **v0.1** | Core: state/ledger/events, git_gate, test_gate, detector, injector, adapter OpenCode T1, generic_proc T2, CLI run/status, fake agent tests | 4–5 ngày |
| **v0.2** | Daemon detach + `serve`, `watch` TUI, `report`, `detect`, `doctor`, PTY T3, notify, adapter Claude | 4–6 ngày |
| **v0.3** | Skill 4 provider + `install-skill`, coverage audit, browser dashboard, packaging PyPI | 3–4 ngày |
| **v1.0** | README + GIF demo 45s + launch | 2 ngày |

**Nguyên tắc:** quay demo **trước** khi package — cái GIF chính là sản phẩm.

**Lưu ý scope:** 3 adapter + TUI + checklist + notification + packaging trong 4 ngày là bất khả thi (đã đánh giá lại). Bản gốc ước lượng thiếu 3–5x.

---

## 18. Quan hệ với `.agents` swarm

| | Swarm (`.agents/`) | waker-ai |
|---|---|---|
| Bản chất | Nhà máy: planner → router → workers → reviewers | Camera + cây gậy |
| Sở hữu model | Có (gọi API/SDK) | Không (wrap CLI bên ngoài) |
| Đơn vị việc | API call / task có `verify_command` | Turn của process CLI |
| Chống báo xong non | `verify_command` fail → không apply + rollback | Gate + kick + resume session |
| Ai ghi file | Chỉ Lead qua `safe_writer` | Agent trực tiếp → checkpoint/revert |
| State | ledger.jsonl append-only | run ledger + session id + checkpoint |
| Phân phối | Runbook cá nhân | Sản phẩm pip install |

**Quan hệ:** bổ trợ, không cạnh tranh. Chain được:

```bash
waker run --tasks overnight.yaml --test "python .agents/tests/test_phase4.py" \
  --max-kicks 8 -- opencode run --auto "chạy swarm cho plan overnight"
```

Swarm sản xuất, waker canh ca đêm. Đúng ca "DeepSeek làm 14 phút rồi chuồn".

**Quyết định repo:** tách repo public riêng. Không import chéo `.agents`. Chỉ **port khái niệm**:

| Lấy từ `.agents` | Dùng cho waker |
|---|---|
| `verify_command` exit 0 | test_gate |
| rollback byte-exact `safe_writer` | checkpoint/revert |
| `run_lock.py` | lock chống 2 supervisor |
| `notify.py` | breaker alert |
| ledger append-only | events.jsonl |

---

## 19. Giới hạn phải nói trước

1. **Agent chat-only, không ghi đĩa** → không có git diff, chỉ còn `verify` + checklist. Vẫn canh được "làm thiếu", khó chứng minh "nói láo". Định vị: *coding agent supervisor*.
2. **T3 false-positive** → agent nghĩ 3 phút là bình thường. Phải đa tín hiệu (screen đổi / file đổi / bytes mới) + log rõ lý do.
3. **Không làm model dốt thành giỏi** → hết kick thì `GAVE_UP` + gọi người.
4. **Baseline đỏ sẵn** → phải dùng fail-to-pass set, không đòi "toàn bộ xanh".
5. **Repo không git** → fallback hash + mtime.
6. **Detect test command có thể sai** → monorepo phải hỏi user.

---

## 20. Acceptance criteria (định nghĩa "đã xong")

### 20.1 Test tự động (không tốn token, chạy 2 giây)

| Test | Kỳ vọng |
|---|---|
| `fake_lazy` (làm T1 rồi exit 0, in "done") | `PARTIAL` → kick ít nhất 1 lần → cuối cùng `DONE` khi fake agent chịu làm hết |
| `fake_liar` (luôn in "all done", không làm gì) | `FALSE_DONE` → kick tới `BREAKER` → `GAVE_UP`, **không bao giờ** exit 0 |
| `fake_tamper` (sửa test cho pass) | `TAMPER` → revert test → kick |
| `fake_freeze` (sleep vô hạn) | `FROZEN` sau `freeze_after` → abort → kick |
| `fake_thrash` (sửa 2 dòng lặp lại) | `THRASH` sau 2 fingerprint giống nhau |
| `fake_blocked` (in `BLOCKED: ...`) | dừng ngay, exit 3, không đốt kick |

### 20.2 Định nghĩa DONE của chính waker

- `pytest` exit 0.
- Tất cả 5 fake agent tests pass.
- `waker status` hiển thị đúng từ `ledger.json`.
- Báo cáo cuối có đủ: task, evidence, test log, số kick, cost.

---

## 21. Câu hỏi mở cần chốt

1. **Tên package PyPI**: `waker-ai` còn trống không? entrypoint `waker` có trùng không?
2. **Chế độ chạy đêm**: `--yes` auto-chốt task list (nhanh, phụ thuộc decompose) hay luôn bắt xác nhận 1 phím? *Đề xuất: auto-chốt + Phase 6.5 audit làm lưới an toàn.*
3. **Notification mặc định**: Windows toast / Telegram / cả hai?
4. **Cost tracking**: parse token usage từ `--format json` của OpenCode — cần xác nhận schema thực tế.
5. **Multi-repo**: 1 waker run có được span nhiều repo không? *Đề xuất v0.1: không.*
6. **`--format json` của `opencode run`**: cần verify cấu trúc event thật (session id, tool call, token usage) trước khi code adapter.

---

## 22. Planner / Decomposer — ai viết test & ai chia checklist

### 22.1 Ai viết test? — Waker **không** sinh code, và đó là thiết kế

Waker chạy trong terminal **không cần** sinh code. `verify` chỉ là **một chuỗi lệnh** được `subprocess` thực thi — dữ liệu, không phải code. Ba nguồn hợp lệ:

| Nguồn | Ai viết | Khi nào dùng |
|---|---|---|
| User đưa | Bạn | `--test "pytest tests/ -q"` — chắc chắn nhất |
| `waker detect` | Máy (deterministic) | đọc `pyproject.toml` / `pytest.ini` / `package.json` / `go.mod` → gợi ý, user xác nhận |
| Agent viết | Chính AI đang được canh | task `test_writer: true` → waker kiểm **red→green** (§10.2) |

**Vì sao waker không tự viết test:** nếu nó sinh test, thì phải có một waker thứ hai đi kiểm chính nó — lại đúng căn bệnh sản phẩm muốn diệt. Waker là **trọng tài**, không phải **thí sinh**.

Hệ quả kiến trúc: không cần LLM trong engine. Toàn bộ "trí tuệ" của waker là **so sánh** và **chạy lệnh**.

### 22.2 Prompt lộn xộn → checklist: mô hình 4 rổ

Prompt thực tế hiếm khi là danh sách. Ví dụ:

> "làm cái app quản lý chi tiêu, có login, thêm/sửa/xoá giao dịch, báo cáo tháng,
> xuất excel, deploy vercel, nhớ viết test, à đừng dùng tailwind, dùng css thuần,
> với lại phải responsive"

Trước khi chia task, phải **phân loại** — vì không phải câu nào cũng là việc:

| Rổ | Ví dụ | Biến thành gì |
|---|---|---|
| **Work item** | "thêm/sửa/xoá giao dịch" | task (scope + verify) |
| **Constraint** | "đừng dùng tailwind" | **negative gate** (kiểm bằng máy) |
| **Preference** | "phải responsive" | context nhét vào wake prompt, ghi rõ *không verify bằng máy được* |
| **Unknown** | "deploy vercel" (thiếu token) | **câu hỏi cho user**, tối đa 3 |

Đây là chỗ plan gốc thiếu: **constraint không phải task**. Nếu nhét "đừng dùng tailwind" thành task, agent sẽ tick xanh mà chẳng ai kiểm.

### 22.3 Pipeline decompose (deterministic trước, LLM sau)

```
P0  Normalize      : strip, tách đoạn, tách dấu chấm/phẩy
P1  Extract rules  : numbered list, bullet, "1)", "và", ";" → candidate items   [0 quota]
P2  Classify       : 1 LLM call, strict JSON schema → 4 rổ                   [1 call]
P3  Build          : tasks.yaml + constraints.yaml + notes + questions
P4  Validate máy   : mỗi task có scope + verify; mỗi task map ≥1 clause gốc;
                     không clause nào bị bỏ rơi
P5  Retry          : nếu P4 báo clause chưa map → 1 call nữa kèm danh sách gap [chỉ khi fail]
P6  Freeze         : user xác nhận (hoặc --yes) → hash → bất biến
```

Ví dụ output của prompt trên:

```yaml
# tasks.yaml
- id: T1
  desc: "Auth: login/logout/session"
  scope: ["src/auth/**", "tests/auth/**"]
  verify: "pytest tests/auth -q"
  source: ["có login"]

- id: T2
  desc: "CRUD giao dịch"
  scope: ["src/tx/**", "tests/tx/**"]
  verify: "pytest tests/tx -q"
  source: ["thêm/sửa/xoá giao dịch"]

- id: T3
  desc: "Báo cáo tháng"
  scope: ["src/report/**"]
  verify: "pytest tests/report -q"
  source: ["báo cáo tháng"]

- id: T4
  desc: "Xuất Excel"
  scope: ["src/export/**"]
  verify: "pytest tests/export -q"
  source: ["xuất excel"]

- id: T6
  desc: "Giao diện CSS thuần + responsive"
  scope: ["src/**/*.css", "src/**/*.tsx"]
  verify: "python -m waker.check no_tailwind src/"
  source: ["đừng dùng tailwind", "dùng css thuần", "phải responsive"]
```

```yaml
# constraints.yaml — gate âm, kiểm bằng máy
- id: C1
  desc: "Không dùng tailwind"
  check: "! grep -rq 'tailwind' package.json src/"
  severity: blocking
```

```yaml
# questions.yaml — không đoán
- id: Q1
  desc: "Deploy Vercel: cần token + project id. Có sẵn chưa?"
  blocks: ["T5"]
```

**Luật vàng:** *không đoán — hỏi.* Tối đa 3 câu hỏi; quá 3 thì dừng và báo user chia nhỏ prompt. Prompt càng lộn xộn càng phải hỏi, không được "sáng tạo" thêm yêu cầu.

### 22.4 Có cần planner của swarm không? — Cần **decomposer**, không cần planner

Phân biệt rõ:

| | Swarm planner | Waker decomposer |
|---|---|---|
| Sản phẩm | plan đa agent: role, wave, budget, route model | checklist task + gate + câu hỏi |
| Chạy khi nào | mỗi task, trước khi giao việc | **1 lần duy nhất** ở đầu run |
| Cần gì | repo map, capability registry, cost routing, approval | prompt + cây thư mục nông |
| Tần suất | mỗi lần chạy | 1 call / run |

Waker **không import** swarm. Nó chỉ mở một interface:

```python
class Planner(Protocol):
    def decompose(self, prompt: str, repo_tree: list[str]) -> PlanBundle: ...
```

Ba backend:

| Backend | Cách chạy | Quota |
|---|---|---|
| `rules` | chỉ P1 deterministic, không LLM | **0** |
| `llm` (mặc định) | 1 call có schema + P4 validate | ~3k token / run |
| `swarm` | shell out `.agents/planner.py --goal ... --out plan.json` rồi map steps → tasks | theo swarm |

`--planner swarm` là **bridge tuỳ chọn**, không phải dependency. Ai không có `.agents/` vẫn dùng bình thường.

### 22.5 Một con hay hai con?

Trực giác "2 con là đẹp" **đúng**, nhưng phải là **2 vai ở 2 thời điểm**, không phải 2 con cùng làm một việc:

| Vai | Thời điểm | Nhiệm vụ | Model |
|---|---|---|---|
| **Decomposer** | t=0, 1 lần | prompt → 4 rổ → tasks.yaml | model khá (hợp đồng do nó đặt) |
| **Coverage Auditor** | cuối run, 1 lần | prompt gốc vs evidence → clause nào chưa phủ | model rẻ |

Chạy **song song 2 con để "lấy ý kiến thứ hai"** là lãng phí: cái kiểm tra decomposer không phải một LLM khác, mà là **schema validator + coverage map** — mạnh hơn và miễn phí. Chỉ khi P4 báo thiếu mới gọi retry 1 lần.

**Chi phí thực tế:**

| Hoạt động | Token / run |
|---|---|
| Decompose | ~3k |
| Coverage audit | ~2k |
| Agent loop (20–40 turn) | 200k – 2M |

→ Planner chiếm **< 1–2%** tổng. Đừng tối ưu chỗ này. Chỗ đốt quota thật là `max_kicks` và `freeze_after`, không phải decompose.

### 22.6 Chống decompose hụt

Ba lớp, rẻ dần:

1. **Schema validator** (0 quota): task thiếu `scope`/`verify` → reject ngay, không cần LLM.
2. **Coverage map** (trong cùng call): mỗi clause gốc phải trỏ tới ≥1 `task.source`; clause mồ côi → reject.
3. **Phase 6.5 audit** (1 call cuối): soi ngược prompt gốc với evidence thật. Chỉ được phát hiện thiếu, **không được** tuyên bố xong.

---

## 23. Contract-first: đầu vào là **hợp đồng**, không phải prompt

### 23.1 Thứ tự ưu tiên đầu vào

| Mode | Input | Token | Ghi chú |
|---|---|---|---|
| **A** | `--tasks tasks.yaml` | **0** | chuẩn nhất, không mơ hồ |
| **B** | `--plan plan.md` (format chấm được) | **0** | người viết tay, `lint` kiểm |
| **C** | `--prompt` + `--planner rules` | **0** | chỉ khi prompt có cấu trúc; **fail closed** nếu thiếu `verify` |
| **D** | `--prompt` + `--planner llm` | ~3k | fallback cho prompt văn xuôi |

Nguyên tắc: **càng viết kỹ càng ít token.** Planner là phao cứu sinh, không phải đường chính.

### 23.2 Format `plan.md` chấm được (người viết được, máy kiểm được)

```markdown
# Plan: quản lý chi tiêu

## T1 — Auth  (phase: 1)
- scope: src/auth/**, tests/auth/**
- verify: pytest tests/auth -q
- done_when: login sai trả 401

## T2 — CRUD giao dịch  (phase: 1)
- scope: src/tx/**, tests/tx/**
- verify: pytest tests/tx -q

## C1 — Không dùng tailwind
- type: constraint
- check: "! grep -rq tailwind package.json src/"
- severity: blocking
```

Ba dòng bắt buộc cho mỗi task: `scope`, `verify`, (tuỳ chọn) `done_when`.

### 23.3 `waker plan lint` — chốt chặn 0 token

Exit ≠ 0 khi:

- task thiếu `scope` hoặc `verify`
- glob không hợp lệ / không match file nào
- id trùng
- `verify` command không tồn tại trên máy
- task không map tới mệnh đề nào của prompt gốc

Exit 0 → freeze + hash → bất biến.

### 23.4 Fail closed — cấm bịa

- `rules` mode **không được** tự sinh `scope`/`verify`. Thiếu → báo lỗi kèm mẫu để user sửa.
- `plan.md` dạng văn xuôi (không có dòng `- verify:`) → từ chối, in hướng dẫn chuyển đổi.
- Lý do: một checklist không verify được = một `DONE` giả chờ sẵn.

### 23.5 Phase ≠ Task

- `phase` chỉ là **nhóm hiển thị** (UI, report).
- Đơn vị kiểm chứng là **task**: 1 task = 1 `verify`.
- Phase quá lớn (nhiều verify) → phải tách thành nhiều task. Nếu không, gate "phase 1 xong" không thể chứng minh bằng máy.

### 23.6 Agent tự viết test → bắt buộc red→green **theo 2 turn**

| Turn | Agent làm gì | Gate đòi |
|---|---|---|
| A | chỉ viết test (`test_writer: true`) | test **đỏ** trên code hiện tại |
| B | implement | test **xanh** |

Lý do: nếu agent viết test **sau** khi code xong, nó sẽ viết test khớp với bug của chính nó → pass giả. Tách 2 turn là cách duy nhất miễn phí để tránh.

Nếu repo đã có test sẵn → ưu tiên trỏ `verify` vào test cũ, bỏ hẳn turn A.

---

## 24. Ánh xạ evidence → task (waker biết "xong" bằng cách nào)

### 24.1 Công thức duy nhất

```python
def done(task, changed_files, verify_results, baseline) -> bool:
    hit    = glob_match(changed_files, task.scope)          # (a) có đụng đúng file không
    passed = verify_results[task.id].exit_code == 0          # (b) lệnh verify có xanh không
    return bool(hit) and passed
```

Chỉ có 2 tín hiệu, cả hai đều **cơ học**:

| Tín hiệu | Nguồn | Trả lời câu hỏi |
|---|---|---|
| `changed_files ∩ task.scope` | `git diff --name-only <baseline>` | "task này có được đụng tới không?" |
| `task.verify` exit code | subprocess | "task này xong thật chưa?" |

Không có semantic matching, không có LLM đoán. Đó là lý do `scope` bắt buộc phải có trong plan.

### 24.2 Ví dụ ánh xạ

```
changed_files = [
  "src/auth/guard.py",
  "tests/auth/test_login.py",
  "docs/api/README.md"
]

T1 scope ["src/auth/**","tests/auth/**"]  → hit ✅  verify pytest tests/auth -q → 0  ⇒ DONE
T2 scope ["src/pay/**"]                   → hit ❌  verify pytest tests/pay  -q → skip ⇒ PENDING
T3 scope ["docs/api/**"]                  → hit ✅  verify grep -q ...            → 0  ⇒ DONE
```

### 24.3 Thay đổi ngoài hợp đồng

File thay đổi nhưng không nằm trong scope nào → `unscoped_changes`:

- Mặc định: **ghi log + hiện UI**, không fail (vì refactor dùng chung là hợp lý).
- `--strict-scope`: fail gate → buộc thêm task cho shared code, hoặc khai báo `allow_unscoped`.
- Lý do phải có: nếu agent sửa `src/shared/utils.py` để làm T1 pass, nó có thể phá T2. Không log là mất dấu.

### 24.4 Luật lint: scope phải rời nhau

```
T1 scope ["src/**"]        ┐
T2 scope ["src/pay/**"]    ┘ → OVERLAP → lint ERROR
```

Hai task trùng scope thì không thể biết thay đổi nào thuộc task nào → `DONE` mơ hồ. Lint bắt buộc tách scope hoặc gộp task.

### 24.5 Wake prompt lấy "đang thiếu gì" từ đâu

| Dòng trong prompt | Nguồn thật |
|---|---|
| `ĐÃ XONG: T1, T4` | `ledger.json` (task có `done == True`) |
| `CHƯA XONG: T2 (Payment), T3 (Ship)` | `tasks.frozen.json` trừ ledger |
| `test_ship.py:31 KeyError` | parse output pytest thật (`FAILED <file>::<name> - <msg>`) |
| `Việc phải làm ngay: T2` | task thiếu đầu tiên theo `depends_on` |
| `Chạy: pytest tests/ -q` | `config.test_command` |
| `Cấm sửa file test` | hằng số trong template |

Không có dòng nào do LLM sinh. "Thông minh" nằm ở chỗ chọn **task thiếu đầu tiên** + **5 lỗi cụ thể nhất**, không phải ở chỗ viết văn.

---

## 25. Test Author — "người thứ 2" viết đề

### 25.1 Tách vai, không gộp call

Cùng một model có thể làm nhiều vai, nhưng **mỗi vai là một phase riêng, một output riêng, một gate riêng**. Không gộp thành một call.

```
prompt
  │
  ├─[A] Decomposer      (chỉ khi prompt mơ hồ)   → tasks.yaml draft
  │
  ├─[B] Test Author     (chỉ khi task chưa có test) → tests/**  (phải ĐỎ)
  │
  ├─ CONTRACT FREEZE    tasks.yaml + hash(tests/**) + user confirm
  │
  ├─[C] Worker          (nhiều turn)              → src/**
  │
  └─[D] Coverage Auditor (1 call cuối)            → clause nào chưa phủ
```

### 25.2 Ranh giới quyền (bắt buộc)

| Vai | Được ghi | Cấm ghi |
|---|---|---|
| Decomposer | `.waker/tasks.draft.yaml` | `src/**`, `tests/**` |
| Test Author | `tests/**` | `src/**`, `.waker/**` |
| Worker | `src/**`, `docs/**` | `tests/**` (đã freeze) |
| Auditor | không ghi | tất cả |

Test Author chạy **trước** Worker và **không thấy code implementation** → tính độc lập đến từ thứ tự, không cần model khác.

### 25.3 Gate của Test Author (trước khi freeze)

- `pytest --collect-only` chạy được (không ImportError)
- Test **ĐỎ** trên code hiện tại
- ≥ 3 assert, không `skip`/`xfail`/`pass` rỗng
- File nằm trong `tests/**`
- Hash toàn bộ `tests/**` ghi vào contract

Pass hết → freeze. Không pass → không cho Worker chạy (fail closed).

### 25.4 Test định nghĩa interface

Test Author viết test gọi API mà nó *mong muốn*. Worker phải implement khớp. Prompt của Worker ghi rõ:

> `tests/**` là hợp đồng interface. Không được sửa test. Nếu tên hàm khác với test, sửa code cho khớp test.

Đây là TDD ở tầng hợp đồng — và là cách duy nhất để "spec" không bị diễn giải lại.

### 25.5 `SUSPECT_TEST` — bảo vệ Worker khỏi đề sai

Nếu ≥ 2 kick liên tiếp mà **toàn bộ** lỗi là `ImportError` / `AttributeError` / collection error trên test đã freeze:

```
diagnose = SUSPECT_TEST
→ dừng, không đốt kick
→ báo: "Test có thể sai (gọi API không tồn tại). Cần người xem."
```

Không có detector này, một test sai sẽ khiến Worker bị đánh 5 lần vô tội.

### 25.6 So sánh 2 mô hình

| | Worker tự viết test (2 turn) | Test Author riêng |
|---|---|---|
| Chống tự chấm bài | tốt (red trước) | **tốt hơn** (độc lập hoàn toàn) |
| Test viết theo hướng có lợi cho AI | có thể | khó hơn |
| Rủi ro | test nông | test sai API → cần `SUSPECT_TEST` |
| Chi phí | 2 turn worker | 1 turn author (rẻ hơn worker) |
| Khi nào dùng | repo nhỏ, task đơn giản | **mặc định** cho task lớn |

Khuyến nghị: **mặc định dùng Test Author**; fallback về "worker tự viết 2 turn" khi Test Author fail gate.

### 25.7 Chi phí

| Vai | Token |
|---|---|
| Decomposer | ~3k (chỉ khi mơ hồ) |
| Test Author | ~5–15k (1 turn agent) |
| Worker | 200k–2M |
| Auditor | ~2k |

→ Test Author < 5% tổng. Đổi lại: worker không còn quyền tự chấm bài.

---

## Phụ lục A — Ghi chú vận hành (đã gặp thật)

1. **Default model có thể chết.** Lần test đầu, `opencode run` (không chỉ định model) trả:
   `ConnectionRefused: Unable to connect. Is the computer able to access the url?`
   → Adapter **bắt buộc** cho phép `--model`, và `doctor` phải ping model trước khi start.

2. **PowerShell hiển thị `NativeCommandError`** khi opencode ghi ra stderr. Không phải lỗi thật. Adapter nên dùng `--format json` và đọc stdout, bỏ qua stderr noise.

3. **`opencode session list`** trả về: `<session_id>\t<title>\t<datetime>` — parse được, dùng cho `waker watch --session`.

4. **Session sống ngoài process.** Đã chứng minh: run 2 (process khác) nhớ `ZX-4471` từ run 1.

---

## Phụ lục B — Vì sao không dùng LLM phán "xong chưa"

Nếu để LLM quyết định trạng thái mỗi vòng:

- Nó có thể bị chính output của agent thuyết phục ("em đã xong").
- Nó không tái lập được: cùng input, khác output → user mất niềm tin.
- Nó đắt: mỗi 2 giây một lần gọi = đốt tiền vô ích.
- Nó **mắc đúng bệnh của con nó đang canh**.

LLM chỉ được dùng ở **2 chỗ biên**, mỗi chỗ 1 lần:
1. Phase 0.5 — decompose prompt → tasks.yaml (có người chốt).
2. Phase 6.5 — coverage audit (chỉ được phát hiện thiếu, không được tuyên bố xong).

Tất cả phần còn lại là **deterministic**.

---

## 26. Planned v2.2 — Grill-Me + Real-time CLI/TUI Checklist

**Status:** Proposal only — chưa triển khai. Đây là plan chi tiết để làm sau v2.0.0.
**Lộ trình:** Grill-Me + status/warnings ưu tiên v2.1; Rich animation/TUI polish ưu tiên v2.2.
**Mục tiêu:** giảm contract sai do prompt mơ hồ, đồng thời làm terminal UI dễ đọc,
gọn và có cảm giác “đang được giám sát thật”.

### 26.1 Nguyên tắc phân vai

```text
Prompt
  -> Agent chatbox: đọc, hỏi lại, phân rã, viết tasks.yaml
  -> User: xác nhận contract
  -> Waker: chỉ giám sát git diff ∩ scope + verify + anti-slop
```

Waker **không đọc prompt gốc để tự hiểu/sinh scope**. Grill-me là lớp
contract-authoring, không phải LLM mới nhét vào watchdog.

### 26.2 Grill-Me flow

1. Agent nhận prompt và phân loại:
   - goal rõ chưa?
   - file/module nào được sửa?
   - verify command là gì?
   - acceptance/test nào chứng minh?
   - credential, môi trường, dữ liệu, deploy có sẵn không?
   - constraint nào bắt buộc?
2. Nếu thiếu, Agent hỏi user 3–5 câu ngắn, ưu tiên câu blocking.
3. Câu trả lời được ghi vào `questions.yaml` hoặc block `questions` trong
   contract:
   ```yaml
   questions:
     - id: Q1
       kind: clarify
       text: "API login dùng session hay JWT?"
       options: ["session", "jwt"]
       blocks: ["T2"]
       status: open
   ```
4. Agent viết `tasks.yaml` với `scope`, `verify`, acceptance và map câu trả lời.
5. `waker lint` fail closed nếu còn câu hỏi `status: open` đang block task.
6. User freeze contract; Waker bắt đầu giám sát.

### 26.3 CLI surface đề xuất

```bash
waker grill --prompt "..."              # in câu hỏi blocking; không tự trả lời
waker grill --tasks .waker/tasks.yaml   # kiểm tra questions còn open
waker plan --grill                      # agent/chatbox flow, chỉ interactive
waker lint --questions                  # fail nếu câu hỏi blocking chưa resolve
waker run --tasks ... --questions .waker/questions.yaml
waker status --questions                # hiển thị câu hỏi đang chờ
```

Quy tắc:

- Không auto-answer, không tự bịa scope.
- Detached mode không treo chờ vô hạn: ghi `questions.yaml`, trả trạng thái
  `BLOCKED`/`WAITING_FOR_INPUT`, exit code rõ ràng.
- `--yes` chỉ dùng để chấp nhận contract **đã có đủ scope/verify/questions
  resolved**, không dùng để bỏ qua câu hỏi blocking.

### 26.4 Dữ liệu cho UI

Ưu tiên đọc từ ledger/events hiện có, chỉ thêm field có nguồn rõ ràng:

```json
{
  "task": "T1",
  "status": "running|pass|fail|blocked",
  "percent": 72,
  "grade": "B",
  "errors": 0,
  "warnings": 3,
  "verify_exit": 0,
  "anti_slop": {"score": 86, "errors": 0, "warnings": 3},
  "attempt": 2
}
```

- `percent`: % evidence hoàn thành, không phải % thời gian.
- `grade`: grade riêng của task nếu đủ dữ liệu; nếu không, kế thừa run grade.
- `attempt`: kick hiện tại của task/run.
- Logs:
  - `kick log`: `kick 0 SLOP`, `kick 1 SLOP`, `kick 2 DONE`.
  - `failure log`: verify failures gần nhất, tối đa 5 dòng.
  - `anti-slop log`: rule, file:line, severity, warning/error count.

### 26.5 `waker watch` layout

Màn hình gọn, ưu tiên nhìn trong 1 terminal 100–120 cột:

```text
╭─ waker · b81c627e ───────────────────────────────────────────────╮
│  CLEANLINESS   ███████████████░░░   76/100   Grade C             │
│  kicks 2/5     pytest PASS          $0.0069   0 errors · 8 warn   │
│  ◐ validating T1 …                                               │
│                                                                  │
│  CHECKLIST                                                       │
│  ✅ T1  Todo CLI         100%  C   0 err   8 warn   verify PASS   │
│  ◐ T2  API adapters       62%  B   0 err   1 warn   running      │
│  ○ T3  Docs                0%  —   —       —        waiting      │
│                                                                  │
│  KICK LOG   0 SLOP  →  1 SLOP  →  2 DONE                         │
│  FAIL LOG   (none in this run)                                   │
│  ANTI-SLOP   TYPE006 ×7  ·  TYPE012 ×1  ·  warnings only          │
╰──────────────────────────────────────────────────────────────────╯
```

Quy ước trạng thái:

- `○` pending: xám, không spinner.
- `◐` running/validating: spinner 4 frame `◐ ◓ ◑ ◒`, 120–180 ms/frame.
- `✅` pass: xanh, flash nhẹ 1 lần rồi đứng yên.
- `✖` fail: đỏ, **bold + blink 2 chu kỳ**, sau đó spinner quay lại và tăng
  `kick`.
- `⏸` blocked: vàng, kèm câu hỏi blocking hoặc lý do.
- `SLOP` đỏ: không được coi là pass dù pytest xanh.

### 26.6 Thành phần UI

| Thành phần | Nguồn dữ liệu | Hành vi |
|---|---|---|
| Quality header | `ledger.quality` | score, grade, errors, warnings, baseline suppressed |
| Progress ring/bar | task evidence | cập nhật mỗi turn, không flicker |
| Spinner | task status | quay khi running, dừng khi pass/fail/blocked |
| Checklist | tasks + scope + verify | percent, grade, errors/warnings, gate |
| Kick log | `events.jsonl` | append `0 SLOP`, `1 SLOP`, `2 DONE` |
| Fail log | verify/test failures | 5 dòng gần nhất, có file:line |
| Anti-slop log | gate findings | group theo rule/family, warning/error |
| Footer | run | cost, elapsed, session, `report.md` |

### 26.7 Hành vi animation

- Chỉ animate phần thay đổi; không clear toàn màn hình mỗi tick.
- Tần suất 4–8 FPS khi running; giảm còn 1–2 FPS khi idle.
- Khi fail:
  1. frame đỏ đậm;
  2. blink 2 lần (150–200 ms/lần);
  3. hiện lý do fail;
  4. spinner tiếp tục và `kick + 1`.
- Khi pass:
  1. dừng spinner;
  2. flash xanh 300 ms;
  3. đổi icon sang `✅`;
  4. cập nhật quality header.
- Tôn trọng:
  - `NO_COLOR`
  - `--no-anim`
  - non-TTY/pipe → plain Markdown, không ANSI
  - terminal hẹp → single-column fallback
  - Windows cp1252 → ASCII fallback

### 26.8 Thứ tự triển khai

**Ưu tiên 1 — Grill-Me contract gate**
1. Chuẩn hóa `Question`/`questions.yaml`.
2. `waker grill` + `waker lint --questions`.
3. Agent/skill flow hỏi user trước khi viết contract.
4. Test: câu hỏi blocking phải chặn `waker run`, câu trả lời phải map được
   task.

**Ưu tiên 2 — Status/quality data**
1. Bổ sung per-task progress vào ledger.
2. `waker status --questions`.
3. `waker status --warnings` + grouped warnings.

**Ưu tiên 3 — Rich watch UI**
1. Header quality + checklist.
2. Spinner/pass/fail transitions.
3. Kick log, fail log, anti-slop log.
4. Compact mode và accessibility.

**Ưu tiên 4 — Polish**
1. `waker explain RULE`.
2. Snapshot tests cho từng trạng thái.
3. Web dashboard dùng cùng data model.

### 26.9 Acceptance tests

- Fake agent: `SLOP → SLOP → DONE` hiển thị đúng 3 dòng kick log.
- Pytest xanh nhưng anti-slop đỏ: task **không** được hiện `✅`.
- Fail hiển thị đỏ, blink, rồi spinner quay lại; pass chuyển xanh.
- Warning không block nhưng hiện đúng count/grade.
- Không có ANSI khi pipe; `NO_COLOR` vẫn đọc được.
- Terminal 80 cột không tràn/cắt mất score/grade.
- Detached mode không treo vì câu hỏi; ghi `questions.yaml` + `BLOCKED`.
- Không auto-answer, không tự sinh scope từ prompt.

### 26.10 Non-goals

- Không đưa LLM vào watchdog để tự hiểu prompt.
- Không auto-answer câu hỏi.
- Không thay thế chatbox agent.
- Không dùng animation quá mức hoặc emoji dày đặc.
- Không ưu tiên web dashboard trước CLI.

### 26.11 Waker Cyber-Deck FX Tiers & Agent Integration

**Status:** **[x] DESIGN APPROVED — CHECKPOINT READY FOR IMPLEMENTATION (v2.2).**
Đây là đặc tả chốt cho TUI/agent integration; chưa phải code production.

#### 26.11.1 Layout & thẩm mỹ TUI

- **Rich Live, 2 cột**:
  - Cột trái 60%: **Tasks Pipeline**.
  - Cột phải 40%: **Watchdog Telemetry**.
  - Đáy: **Realtime Event Stream** + **Keybind Footer**.
- Footer mặc định:
  ```text
  [q] Quit   [p] Pause   [v] Diff   [l] Full Log
  ```
- Header/telemetry phải có dữ liệu sống còn:
  - **Agent Identity**: `[OpenCode · DeepSeek]` (lấy từ run config/model).
  - **Goal**: task description hoặc prompt gốc đã freeze.
  - **Scope diff thực tế**: `store.py +14 -3`, `0 out-of-scope`.
  - Task %, errors, warnings, verify result, grade.
- **100% dữ liệu thật** từ `ledger.json`, `events.jsonl`, `run.json` và git diff:
  - Không bịa T2/T3 khi run chỉ có T1.
  - Có **empty-state** đẹp khi chỉ có 1 task hoặc chưa có diff.
  - Cost chỉ hiện `actual`; nếu muốn số nhảy giữa các usage event thì ghi rõ `~estimated`, và reconcile khi có cost thật.
- Theme:
  - Tokyo Night / Catppuccin.
  - Border tối: `#24283b`.
  - Active blue: `#7aa2f7`.
  - Pass green: `#73daca` (hoặc `#9ece6a`).
  - Slop red: `#f7768e`.
  - Dim text: `#565f89`.
- Cleanliness bar:
  - Dạng mỏng: `▰▰▰▰▰▰▰▱▱`.
  - Xanh: A/A+.
  - Vàng: B/C.
  - Đỏ nhấp nháy **2 nhịp**: `<70` hoặc có Slop.
  - Cập nhật ngay khi Waker xong review checkpoint; không đợi hết run.

#### 26.11.2 Cinematic FX tiers

Tách tuyệt đối **data poll** và **animation tick**:

```text
data poll:      500–1000 ms   (đọc ledger/events từ đĩa)
animation tick: 80–120 ms     (8–10 FPS)
Rich refresh:   8–10 FPS
```

Các FX:

- **Border Beam**: xung điện Cyan chạy 1 vòng khép kín quanh viền bo góc
  khi `running`; dừng khi `DONE`/`FAIL`/`BLOCKED`.
- **Active Worker Spinner**: `⠋` xoay, màu Cyan, chứng minh Coder đang chạy.
- **Laser Shimmer**: vệt sáng quét ngang thanh Cleanliness.
- **Braille Spark Reactor**: bắn 3–5 hạt `✦ * · .` khi có event mới, tự tắt
  sau ~400 ms.
- FX không được che log, không nhấp nháy vô hạn, không bắn hạt khi đang đọc
  event stream.
- Toàn bộ FX hỗ trợ:
  - `--no-fx`
  - tắt tự động trên SSH / `NO_COLOR` / non-TTY
  - fallback terminal 80 cột
  - ASCII fallback nếu thiếu Braille/emoji
- **Bỏ mouse wave khỏi CLI**; hiệu ứng sóng theo chuột để dành cho Web UI.

#### 26.11.3 Tích hợp Agent Chatbox

- **Auto-Popup Window (`--window`)**:
  - Khi gọi từ OpenCode/Claude Code/Cursor trong môi trường có GUI.
  - Waker tự mở terminal phụ:
    ```bat
    start waker watch --repo . --run <id> --window
    ```
  - Chatbox chính vẫn giữ nguyên; cửa sổ phụ chỉ quan sát.
  - Chỉ mở khi:
    - có `--window`
    - là interactive TTY
    - không phải SSH/CI
  - Không mở nhiều cửa sổ trùng run; có thể focus/attach cửa sổ đã có.
  - Khi `DONE`, có thể giữ cửa sổ để user đọc report hoặc tự đóng theo
    `--window-close=done`.

- **Slash command `/waker`**:
  - Skill/command cho OpenCode (và tương đương cho Claude Code nếu hỗ trợ).
  - Nhiệm vụ:
    - mở/attach Cyber-Deck cho run hiện tại;
    - hỏi user nếu thiếu run id;
    - fallback mini-bar nếu không có GUI.
  - Không phải LLM trong watchdog; chỉ là lớp UX gọi CLI.

- **Fallback Mini-bar**:
  - Một dòng gọn cho SSH/pipe/không GUI:
    ```text
    waker b81c627e · C 76/100 · 2/5 kicks · 0 err · 8 warn · DONE
    ```
  - Có thể chèn vào câu trả lời chatbox; không ANSI trong pipe.
  - `waker setup` cài skill/command tương ứng.

#### 26.11.4 Checkpoint triển khai

- [x] Chốt layout 2 cột, theme, dữ liệu thật, empty-state.
- [x] Chốt FX tiers, tần số, `--no-fx`, SSH/NO_COLOR fallback.
- [x] Chốt agent integration: `--window`, `/waker`, mini-bar.
- [x] Chốt bỏ mouse wave khỏi CLI.
- [ ] Implement data model/ViewModel + `waker status --warnings`.
- [ ] Implement Rich Live layout + FX.
- [ ] Implement `--window` + slash command + mini-bar.
- [ ] Snapshot tests, Windows/SSH/80-column tests.
- [ ] Record demo 15s từ CLI thật.

**Checkpoint: APPROVED — sẵn sàng triển khai sau khi chốt thứ tự P0–P4.**

---

## 27. Approved — Grill-Me & Timeout Profiles

**Status:** **[x] DESIGN APPROVED — chốt ngày 19/11/2026.**
Đây là đặc tả chốt cho vòng phát triển tiếp theo; chưa code production.

**Mục tiêu:**

- Giảm contract sai do prompt mơ hồ, nhưng **không làm phiền user ở mọi prompt**.
- Cho user chọn/chỉnh phase và ngân sách thời gian, kết hợp đề xuất thông minh
  từ AI với quyền quyết định cuối cùng của con người.
- Tách rõ 4 loại timeout đang bị gộp: turn, verify, freeze và toàn run.
- Giữ nguyên nguyên tắc cốt lõi: **AI đề xuất, user freeze contract, Waker
  kiểm chứng bằng evidence trên đĩa.**

**Release target:**

- **v2.2.0:** Grill-Me instruction-only + phase selection/review + profile +
  hiển thị budget + tách rõ các loại timeout; chưa hard-stop theo phase.
- **v2.3.0:** hard enforcement đầy đủ cho phase budget, `resume --extend`
  nâng cao, dữ liệu lịch sử để gợi ý budget, và `waker grill`/`questions.yaml`
  nếu instruction vẫn chưa đủ.
- Không đưa AI vào watchdog để tự đổi contract giữa run.

### 27.1 Grill-Me — chỉ bật khi prompt mơ hồ

Grill-Me là **conditional gate**, không phải bước bắt buộc. Mặc định phải là:

> **Prompt đủ rõ → silent-pass, 0 câu hỏi, đi thẳng vào `waker plan`.**

Chỉ bật khi user yêu cầu lập kế hoạch/chạy một task **và** thiếu một trong các
thông tin blocking:

1. **Goal** — không xác định được kết quả cuối cùng.
2. **Scope** — không biết file/module/thư mục nào được sửa.
3. **Verify** — không có lệnh test hoặc acceptance chứng minh hoàn thành.
4. **Input bắt buộc** — thiếu credential, môi trường, dữ liệu hoặc quyền deploy
   mà nếu thiếu thì không thể bắt đầu.

Không bật Grill-Me khi:

- User chỉ hỏi kiến thức, giải thích, review code, debug hoặc đọc trạng thái.
- Task nhỏ và rõ: sửa typo, đổi màu, thêm một nút đã có đủ scope/verify.
- Prompt đã đủ goal + scope + verify + acceptance.
- Chỉ thiếu preference thẩm mỹ hoặc lựa chọn kỹ thuật nhỏ mà agent có thể tự
  quyết định an toàn.
- Đang có run Waker hoạt động; chỉ báo trạng thái, không hỏi lại.

Quy tắc hỏi:

- Tối đa **3 câu**, một lượt duy nhất.
- Chỉ hỏi câu blocking; không hỏi preference.
- Không tự trả lời, không tự bịa scope/verify.
- Nếu user trả lời “tùy bạn” cho phần không thể verify: ghi thành `preference`,
  không biến thành task.
- Nếu sau 3 câu vẫn mơ hồ: dừng và đề nghị user chia nhỏ task.
- Nếu chỉ thiếu preference: tự chọn mặc định, ghi rõ giả định, không hỏi.

Format gợi ý:

```text
Grill-Me — cần chốt 2 điểm trước khi freeze contract:

1. Scope: auth sửa trong src/auth/** hay cả src/api/**?
2. Verify: dùng pytest tests/auth -q hay cần thêm case login sai trả 401?

Trả lời xong mình mới tạo tasks.yaml.
```

#### 27.1.1 Nơi ghi instruction

- **Bắt buộc:** thêm mục Grill-Me vào
  `.opencode/skills/waker/SKILL.md`, trước bước `waker plan`.
- **Tuỳ chọn:** thêm một rule ngắn vào `AGENTS.md` của repo nếu muốn áp dụng
  cả chat thường, không chỉ khi gọi `/waker`.
- **Không mặc định** sửa `C:\Users\tuank\AGENTS.md` cho mọi project, vì sẽ làm
  agent hỏi quá nhiều ở việc đơn giản. Chỉ làm nếu user chủ động yêu cầu.
- Instruction-only là **soft gate**. Muốn chặn thật phải làm
  `questions.yaml` + `waker grill` + `waker lint --questions` (mục 27.9).

### 27.2 Chọn phase: AI draft + human freeze

Phase là nhóm công việc để điều phối và tính budget, **không thay thế task**.
Đơn vị kiểm chứng vẫn là task: mỗi task có `scope` và `verify` riêng.

Ba chế độ:

| Mode | Khi dùng | Hành vi |
|---|---|---|
| `--phases none` | Task nhỏ, một mạch | Một phase ngầm định `P1`, không hỏi thêm |
| `--phases manual` | User đã biết cách chia | User tự viết `phases` và gán `phase` cho task |
| `--phases auto` | Dự án vừa/lớn, nhiều mảng | Rule/AI đề xuất, user duyệt trước khi freeze |

`auto` không có nghĩa là AI tự chạy. Luôn là:

```text
AI/rules đề xuất phase
  -> in bảng phase + task + budget
  -> user chọn Enter / sửa / manual / đổi profile
  -> freeze contract
  -> Waker chạy
```

Nguồn đề xuất theo thứ tự ưu tiên:

1. `phase` đã có trong prompt (`Phase 1: ...`, `Phase 2: ...`).
2. Nhóm theo module/scope và dependency của task.
3. Rule-based: số task, độ rộng scope, test command, verify timeout.
4. AI/OpenCode chỉ khi user chọn `--via opencode`; output phải đúng schema,
   không được tự bịa scope/verify.
5. Lịch sử run (v2.3): thời gian thực tế theo phase/task để gợi ý budget,
   không dùng lời hứa của LLM.

Giới hạn MVP:

- Tối đa **6 phase**, không nested phase.
- Mỗi task thuộc đúng một phase.
- Không có phase rỗng.
- Không cho AI đổi phase giữa run.
- Không tự động chuyển task sang phase khác khi một phase timeout.

### 27.3 Contract schema đề xuất

```yaml
profile: large

phases:
  - id: P1
    name: Foundation
    budget: 45m
  - id: P2
    name: Core features
    budget: 2h
  - id: P3
    name: Integration + UI
    budget: 45m
  - id: P4
    name: Verify and polish
    budget: 30m

tasks:
  - id: T1
    phase: P1
    scope: ["src/core/**", "tests/core/**"]
    verify: "pytest tests/core -q"
    verify_timeout: 10m
  - id: T2
    phase: P2
    scope: ["src/features/**", "tests/features/**"]
    verify: "pytest tests/features -q"
```

Quy ước:

- `budget` chấp nhận `30s`, `15m`, `2h`; lưu nội bộ bằng giây.
- `verify_timeout` là tuỳ chọn theo task; mặc định lấy từ profile.
- `profile` chọn bộ timeout mặc định; user được override từng phase/task.
- `phases` là một phần của contract đã freeze; sửa sau khi start là `TAMPER`.
- Task cũ không có `phases` tương thích ngược: toàn bộ nằm trong `P1` ngầm định.
- Tổng budget các phase + reserve mặc định 15% phải ≤ `max_wall_clock`.
- Nếu phase không có budget riêng, chia theo profile và số task; user vẫn phải
  xác nhận trước khi freeze.

### 27.4 Timeout profiles

Giữ nguyên hành vi hiện tại làm mặc định `medium`; thêm profile cho việc lớn:

| Profile | `turn_timeout` | `max_wall_clock` | `verify_timeout` | `freeze_after` | `max_kicks` |
|---|---:|---:|---:|---:|---:|
| `small` | 5m | 20m | 2m | 3m | 3 |
| `medium` | 15m | 90m | 5m | 5m | 5 |
| `large` | 30m | 5h | 15m | 10m | 8 |
| `overnight` | 45m | 8h | 30m | 15m | 12 |

Quy tắc:

- `medium` phải giữ đúng default hiện tại để không phá backward compatibility.
- `large`/`overnight` không được mở vô hạn; vẫn giữ cost guard và stall detector.
- `turn_timeout` là giới hạn một lượt agent; `max_wall_clock` là toàn run.
- `verify_timeout` áp dụng cho một lệnh test; timeout test không được tự động
  coi là code sai nếu chưa có evidence khác.
- `freeze_after` phải đủ dài cho build/test im lặng; nếu không, dùng
  `--no-freeze-probe` có kiểm soát và ghi event.
- User có thể override bằng flag hiện có; mọi override phải được ghi vào
  `run.json` và hiển thị trong UI/report.

### 27.5 Phase budget enforcement

Đây là thiết kế đích cho v2.3.0. v2.2.0 chỉ hiển thị phase/budget và cảnh báo
mềm; chưa được tự ý hard-stop giữa run nếu chưa bật tính năng.

Trạng thái phase được lưu trong `run.json`/events, không chỉ hiển thị:

```text
phase_started      P2, budget 2h
budget_warning     P2, remaining 12m
phase_completed    P2, elapsed 1h48m
phase_timeout      P2, remaining tasks T5, T6
budget_extended    P2, +30m, approved_by user
```

Hành vi:

- Khi vào phase: ghi `phase_started`; inject phase hiện tại + remaining budget
  vào wake prompt.
- Ở **80% phase budget**: ghi `budget_warning`; nhắc agent ưu tiên task blocking,
  không mở scope mới.
- Ở **100% phase budget**: dừng ở ranh giới turn với diagnosis `TIMEOUT`,
  không gộp chung vào `BREAKER`; báo rõ phase nào, task nào còn thiếu.
- `turn_timeout` vẫn có thể kill giữa turn; phase budget chỉ chặn ở turn
  boundary để tránh cắt ngang file write.
- Không tự skip phase hoặc tự chuyển task sang phase sau.
- `waker resume <run> --extend 30m` được tăng budget phase hiện tại và
  `max_wall_clock` tương ứng, ghi `budget_extended`; không reset evidence.
- Nếu hết `max_kicks` hoặc cost guard trước phase budget, giữ nguyên
  `BREAKER`/lý do tương ứng; không báo nhầm là timeout.

Thứ tự ưu tiên khi hết ngân sách:

```text
TAMPER / VAULT_TAMPER
  > BLOCKED / FROZEN
  > DONE
  > phase TIMEOUT
  > max_kicks / max_cost BREAKER
  > PARTIAL
```

### 27.6 UI và CLI

CLI surface đề xuất:

```bash
waker plan --prompt "..." --repo . --phases auto
waker plan --prompt "..." --repo . --phases manual
waker plan --prompt "..." --repo . --phases none
waker plan --prompt "..." --repo . --phases auto --json
waker plan --prompt "..." --repo . --via opencode --phases auto
waker start --tasks .waker/tasks.yaml --profile large
waker status --repo . --budget
waker resume <run_id> --extend 30m
```

#### Chatbox-first (surface chính)

User thường ở trong chatbox, không phải terminal tương tác. Vì vậy surface
chính là hội thoại; phím TTY chỉ là fallback.

Agent gọi `waker plan --json` rồi trả lời:

```text
Mình đề xuất 3 phase (profile overnight, cap 8h):

P1  Auth & JWT       T1–T3   45m
P2  Stripe Payment   T4–T7   2h
P3  E2E & Security   T8–T9   30m

Gõ "ok" hoặc "1" để chạy; hoặc nói muốn sửa, ví dụ:
"tăng P2 lên 3h, P1 còn 30m".
```

- Task lớn: **không start** cho đến khi user trả lời rõ ràng `ok` / `1` / `chạy`.
- User sửa bằng ngôn ngữ tự nhiên: agent map yêu cầu → sửa `tasks.yaml` →
  chạy lại lint → in diff ngắn → xác nhận → mới được start.
- Không cần parser ngôn ngữ tự nhiên trong core; agent là lớp hội thoại,
  contract + lint là lớp kiểm chứng.
- Non-TTY/chatbox: in plan/JSON rồi exit; tuyệt đối không chờ phím.
- `--yes`: chỉ dùng khi phase plan hợp lệ, không còn câu hỏi blocking;
  phải ghi `approved_by: --yes` vào event.
- Nếu AI/rules không đề xuất được: fallback `manual`, không fail open.

#### Small-task fast path

Chỉ khi user đã gọi `/waker`, prompt rõ goal + scope + verify, tối đa 2 task,
1 phase, không có câu hỏi blocking:

- Agent được tự chạy ngầm ngay, không hỏi phase.
- Vẫn phải tạo contract, lint sạch, và ghi `approved_by: /waker-fast-path`.
- Nếu thiếu scope/verify hoặc có >2 task → quay lại review/Grill-Me.
- Không áp dụng fast path cho dự án lớn hoặc prompt mơ hồ.

#### Terminal TTY fallback

Khi chạy `waker plan` trực tiếp trong terminal, vẫn có thể dùng:

```text
[Enter] Chấp nhận   [e] Sửa   [p] Đổi profile   [m] Manual   [q] Hủy
```

- `Enter`: chỉ freeze khi validation sạch.
- `e`: sửa phase/task/budget; có thể mở `$EDITOR`.
- `p`: đổi profile, tính lại budget nhưng vẫn phải xác nhận.
- `m`: in template manual; không tự điền scope/verify.

UI Cyber-Deck:

- Thêm dòng phase trong telemetry hoặc header:
  ```text
  PHASE 2/4  Core features   01:12:20 / 02:00:00  [########---]
  ```
- Màu: xanh khi còn nhiều budget, vàng từ 80%, đỏ từ 95%.
- Event stream hiển thị `budget_warning`, `phase_timeout`, `budget_extended`.
- Compact 80 cột gộp phase + budget thành một dòng; không làm tràn footer.
- Plan review dùng dữ liệu thật từ contract, không hiển thị budget giả.

### 27.7 Thứ tự triển khai

1. **Grill-Me instruction-only** trong `SKILL.md`; test thủ công các prompt
   rõ/mơ hồ. Không sửa core.
2. **Contract schema + validation**: `phases`, `profile`, `verify_timeout`;
   backward compatibility với task cũ.
3. **Plan selection/review**: `--phases none|manual|auto`, bảng review,
   `--yes` an toàn; AI/rules chỉ đề xuất.
4. **Engine phase tracking**: phase elapsed, soft warning, hard timeout,
   `TIMEOUT` diagnosis, `resume --extend`.
5. **UI tích hợp**: phase budget row, warning colors, event stream, compact.
6. **Tests + docs + release**: unit/integration/snapshot; cập nhật README,
   skill, CHANGELOG.

Không được gộp bước 1 vào core code; instruction-only phải ship trước để kiểm
tra hành vi thực tế của chatbox.

### 27.8 Acceptance tests

Grill-Me:

- Prompt đủ scope/verify → **0 câu hỏi**, đi thẳng.
- Prompt “sửa bug login” → hỏi tối đa 3 câu blocking.
- Prompt lớn mơ hồ → hỏi 3 câu; nếu vẫn mơ hồ thì yêu cầu chia nhỏ.
- User trả lời “tùy bạn” → ghi preference, không bịa task/scope.
- Không tự trả lời câu hỏi; không gọi `waker plan` khi còn câu hỏi blocking.

Phase selection:

- `none` tạo đúng một phase ngầm định.
- `manual` giữ nguyên phase user nhập.
- `auto` chỉ đề xuất; user chưa duyệt thì chưa freeze/chạy.
- Task không có phase được gán phase mặc định; phase rỗng bị reject.
- Tổng budget vượt `max_wall_clock` bị reject, không tự cắt.
- Sửa `tasks.yaml` sau freeze → `TAMPER`.

Chatbox interaction:

- Prompt lớn: agent in phase plan; gõ `ok` mới start.
- User gõ “tăng P2 lên 3h”: agent sửa YAML, lint lại, xác nhận đúng budget.
- Prompt nhỏ rõ + `/waker`: fast path chạy không hỏi phase.
- Prompt nhỏ nhưng thiếu scope/verify: không fast path; hỏi Grill-Me.
- Non-TTY/chatbox: không chờ phím, không treo subshell.
- Sửa phase bằng lời không được làm mất scope/verify của task.

Timeout:

- `small` timeout đúng `turn_timeout`; `large` không bị giới hạn 15m.
- Phase đạt 80% sinh `budget_warning`, không kill giữa turn.
- Phase đạt 100% dừng với `TIMEOUT`, report còn task.
- `resume --extend` tăng budget và chạy tiếp, không reset evidence.
- `verify_timeout` được ghi riêng; test timeout không bị báo là code fail.
- `freeze_after` không kill oan build/test im lặng ở profile lớn.
- `max_kicks`/cost guard vẫn thắng nếu hết trước phase budget.

UI:

- 120 cột hiển thị phase + budget rõ; 80 cột không tràn footer.
- `NO_COLOR`/SSH/non-TTY fallback vẫn đọc được phase, budget, timeout reason.
- `waker status --budget` khớp `run.json`/events, không dùng số ước lượng
  như số thật.

### 27.9 Code-enforced Grill-Me (deferred)

Nếu instruction-only vẫn bị bỏ qua, làm theo §26.8:

- Chuẩn hoá `Question` + `questions.yaml`.
- `waker grill --prompt`, `waker lint --questions`.
- `waker run` fail closed nếu còn câu hỏi blocking.
- Không auto-answer, không tự sinh scope từ prompt.
- `--yes` không được dùng để bỏ qua câu hỏi blocking.

Đây là **v2.3.0**, không chặn v2.2.0.

### 27.10 Non-goals

- Không Grill-Me mọi prompt.
- Không để AI tự chọn phase/budget rồi chạy không cần user duyệt.
- Không đổi phase, task hoặc budget giữa run mà không có event/approval.
- Không dùng LLM trong watchdog để tự hiểu prompt gốc.
- Không mở timeout vô hạn; vẫn phải có cost guard và stall detection.
- Không biến phase thành đơn vị verify; verify vẫn là task.
- Không thêm nested phase hoặc phase tree trong MVP.
- Không hiển thị budget ước lượng như thể là số liệu thật.

### 27.11 Release gate

- [ ] Grill-Me instruction trong `SKILL.md`.
- [ ] Schema phase/profile + validation.
- [ ] Review phase auto/manual + `--yes` an toàn.
- [ ] Engine phase budget + `TIMEOUT` + `resume --extend`.
- [ ] UI phase row + compact fallback.
- [ ] Acceptance tests xanh; full pytest 100%.
- [ ] README, CHANGELOG, skill docs cập nhật.
- [ ] Demo: prompt mơ hồ → Grill-Me; prompt rõ → 0 câu hỏi.
- [ ] Demo: phase budget warning → timeout → extend → chạy tiếp.

**Execution plan:** [`docs/GRILL_ME_TIMEOUT_EXECUTION_PLAN.md`](docs/GRILL_ME_TIMEOUT_EXECUTION_PLAN.md)

**Checkpoint: RELEASED — v2.3.0 published to PyPI and GitHub.**

---

## 28. Roadmap: Aeneas Protocol — On-Demand Semantic Gatekeeper (Cold-Standby LLM Arbiter)

### 28.1 Bối cảnh & Vấn đề giải quyết (Tại sao cần Aeneas khi đã có Anti-Slop & Sandbox?)
Waker đã giải quyết triệt để ~90% lỗi kỹ thuật và hallucination phổ biến bằng:
- **Anti-Slop Engine:** Chặn nuốt lỗi (`except: pass`), chặn test assertion rỗng, cấm lạm dụng dummy mock bằng deterministic AST/regex rules.
- **Sandboxed Coder & Isolated Worktree:** Đảm bảo worker không làm ô nhiễm host và đo lường exit code khách quan.
- **Deterministic Watchdog:** Đo PID, timeout budget, heartbeat, exit code `0/1`.

**Khoảng trống còn lại (The 10% Semantic Gap):**
1. **Lạc đề nghiệp vụ (Semantic Drift / False Green):**
   - Coder viết test pass 100%, không vi phạm anti-slop, exit code `0`, nhưng **hiểu sai hoặc làm ngược yêu cầu bài toán ban đầu (Prompt Intent)**.
   - Deterministic rules không thể đọc hiểu ngôn ngữ tự nhiên để đối chiếu yêu cầu với git diff.
2. **Xung đột hợp đồng liên phase (Cross-Phase Architectural Collision):**
   - Từng phase chạy độc lập trong worktree đều xanh, nhưng khi ghép nối lại có nguy cơ làm gãy data contract ngầm của phase trước đó.
3. **Bế tắc tự sửa lỗi (Coder Retry Deadlock):**
   - Khi Coder sửa fail $\ge 2$ lần, việc ném toàn bộ log terminal thô khiến Coder dễ bị luẩn quẩn trong vòng lặp ảo giác.

### 28.2 Nguyên lý thiết kế: Cold-Standby & Zero-Overhead (Chi phí tối thiểu)
- **KHÔNG chạy 24/7:** Aeneas ở trạng thái ngủ đông (dormant / cold-standby), chi phí tài nguyên = $0 khi pipeline chạy bình thường.
- **Zero-trust & Veto Power:** Có quyền bác bỏ (Reject) hoặc cách ly (Quarantine) worktree nếu vi phạm hợp đồng nghiệp vụ hoặc sai lệch yêu cầu.
- **Trọng tài theo yêu cầu (On-Demand Arbitrator):** Chỉ được đánh thức dưới đúng 2 điều kiện kích hoạt ngặt nghèo.

### 28.3 Cơ chế kích hoạt (2 Trigger Gates)
1. **Gate 1 — Circuit Breaker Diagnosis (Kê đơn thuốc khi bế tắc):**
   - **Kích hoạt khi:** Worker chạy 1 task bị fail test $\ge 2$ lần liên tiếp.
   - **Nhiệm vụ:** Aeneas đọc git diff + failure log, sinh bản chẩn đoán súc tích (tối đa 3 gạch đầu dòng) chỉ rõ nguyên nhân gốc rễ và hướng sửa để Coder fix dứt điểm trong 1 turn, tránh đốt token vô nghĩa.
2. **Gate 2 — Final Semantic Sanity Gate (Thẩm định ngữ nghĩa trước khi Merge):**
   - **Kích hoạt khi:** Toàn bộ test suite đã pass (exit code 0), trước khi thực hiện merge nhánh vào `main`.
   - **Nhiệm vụ:** Đối chiếu Task Contract / Initial Prompt với tổng thể Git Diff.
   - **Phán quyết:**
     - `VERDICT: APPROVE` kèm chữ ký JSON -> Waker tiến hành merge.
     - `VERDICT: REJECT / QUARANTINE` nếu phát hiện sai lệch yêu cầu nghiệp vụ hoặc sửa lén ngoài scope contract.

### 28.4 Khả năng mở rộng tương lai (Room for Improvement)
- Tương thích cắm model local siêu nhẹ fine-tuned theo Hiến pháp (như `KV-Aeneas` 1.5B GGUF chạy offline qua Ollama/llama.cpp) hoặc fallback qua OpenCode CLI (`glm-5.3-flash-free` / `deepseek-v4.1-flash-free`).
- Tạo tiền đề cho kiến trúc Swarm 3 tầng hoàn chỉnh:
  - `KV-Zeus` (Strategy / Task DAG Planner)
  - `Waker Engine` (Deterministic Harness & Process Isolation)
  - `KV-Aeneas` (On-Demand Semantic Gatekeeper & Arbitrator)
