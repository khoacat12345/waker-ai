# Execution Plan — Grill-Me & Timeout Profiles

**Status:** READY FOR APPROVAL — chưa bắt đầu code.
**Design:** [`plan.md` §27](../plan.md#27-approved--grill-me--timeout-profiles)
**Baseline:** `main` at `ca23827`; full pytest must be green before E0 starts.
**Release:** v2.2.0 cho phần cơ bản; v2.3.0 cho phase-budget enforcement đầy đủ.

## Nguyên tắc thực thi

- Làm đúng thứ tự E0 → E7 cho v2.2.0; E8 chỉ bắt đầu sau khi v2.2.0 được duyệt.
- Mỗi phase là một commit riêng, không trộn code core với UI/docs nếu không cần.
- Test targeted sau mỗi phase; full pytest ở E0, E5 và E7.
- Không đổi version, không tag, không publish nếu chưa có lệnh rõ ràng.
- Không để AI tự chọn phase/budget rồi chạy; luôn có human freeze.
- Task cũ không có `phases` phải chạy y như trước.
- Không reset evidence, không đổi contract giữa run.

## Bản đồ phụ thuộc

```text
E0 Baseline
  ├─ E1 Grill-Me instruction (độc lập, ship sớm)
  └─ E2 Budget/profile foundation
        └─ E3 Contract schema + planner
              └─ E4 Plan modes + review
                    └─ E5 Timeout runtime + TIMEOUT
                          └─ E6 UI phase/budget
                                └─ E7 v2.2.0 release gate
                                      └─ E8 v2.3.0 phase enforcement
```

---

## E0 — Baseline & guardrails

**Mục tiêu:** biết chính xác trạng thái hiện tại trước khi sửa.

**Việc làm:**

1. `git status --short`, `git rev-parse --short HEAD`; xác nhận HEAD `ca23827`.
2. Chạy full pytest; lưu kết quả baseline.
3. Chụp `waker plan --help`, `waker start --help`, `waker resume --help`.
4. Nếu có run timeout thật: lưu `run.json` + 20 dòng cuối `events.jsonl`.
5. Ghi rõ hiện trạng 4 timeout: `turn_timeout`, `max_wall_clock`,
   `verify_timeout`, `freeze_after`.

**Files:** không sửa code; chỉ ghi nhận.

**Gate:** full pytest xanh; worktree sạch; user xác nhận bắt đầu E1.

**Ước lượng:** 0.25 ngày.

---

## E1 — Grill-Me instruction-only

**Mục tiêu:** chatbox chỉ hỏi lại khi prompt thật sự mơ hồ.

**Việc làm:**

1. Thêm mục `Grill-Me` vào `.opencode/skills/waker/SKILL.md`, trước bước
   `waker plan`.
2. Nêu rõ:
   - prompt đủ rõ → silent-pass, 0 câu hỏi;
   - thiếu goal/scope/verify/input blocking → tối đa 3 câu, một lượt;
   - không hỏi preference;
   - không tự bịa scope/verify;
   - sau 3 câu vẫn mơ hồ → yêu cầu chia nhỏ task.
3. Thêm ví dụ ngắn: prompt rõ, prompt mơ hồ, prompt chỉ thiếu preference.
4. Không sửa core, không thêm LLM call.

**Files:**

- `.opencode/skills/waker/SKILL.md`
- `docs/GRILL_ME.md` (nếu cần giải thích dài; SKILL vẫn là nguồn chính)

**Acceptance thủ công:**

- Prompt rõ → 0 câu hỏi.
- “Sửa bug login” → tối đa 3 câu blocking.
- Prompt lớn mơ hồ → hỏi đủ ý, không tự chốt.
- User trả lời “tùy bạn” → ghi preference, không tạo task giả.
- Không gọi `waker plan` khi còn câu hỏi blocking.

**Commit:** `docs(skill): add conditional Grill-Me gate`

**Ước lượng:** 0.5 ngày.

---

## E2 — Budget/profile foundation

**Mục tiêu:** có nguồn sự thật duy nhất cho profile và duration, chưa đổi hành vi
engine.

**Việc làm:**

1. Tạo `src/waker/budget.py`:
   - `PROFILES`: small/medium/large/overnight đúng bảng §27.4;
   - `parse_duration("45m" | "2h" | "30s")`;
   - `resolve_profile(name, overrides)`;
   - `validate_phase_budget(phases, profile, reserve=0.15)`.
2. `medium` phải khớp default hiện tại: 15m/90m/5m/5m/5 kicks.
3. Thêm `tests/test_budget.py`: parse, profile values, tổng budget vượt cap,
   reserve, override.
4. Chưa nối vào engine/CLI.

**Files:**

- `src/waker/budget.py` (mới)
- `tests/test_budget.py` (mới)

**Gate:** unit tests xanh; không có thay đổi hành vi runtime.

**Commit:** `feat(budget): add timeout profiles and phase budget validation`

**Ước lượng:** 1 ngày.

---

## E3 — Contract schema + planner

**Mục tiêu:** phase/profile/verify_timeout trở thành một phần contract hợp lệ và
tương thích ngược.

**Việc làm:**

1. `src/waker/models.py`:
   - thêm `PhaseSpec(id, name, budget_seconds)`;
   - thêm `Task.verify_timeout: float | None`;
   - thêm `PlanBundle.phases`.
2. `src/waker/planner.py`:
   - đọc top-level `profile`, `phases`, task `verify_timeout`;
   - task không có `phase` → gán phase mặc định `P1`;
   - giữ nguyên cách đọc `tasks.yaml` cũ;
   - lint lỗi: phase rỗng, trùng ID, task trỏ phase không tồn tại, quá 6 phase,
     budget âm/không hợp lệ, tổng vượt cap.
3. `to_dict/from_dict` cập nhật để report/JSON không mất dữ liệu.
4. Tests: load YAML cũ, YAML mới, invalid phase, round-trip, hash stability.

**Files:**

- `src/waker/models.py`
- `src/waker/planner.py`
- `tests/test_planner.py`
- `tests/test_state.py` (nếu contract serialization chạm state)

**Gate:** task cũ chạy không đổi; contract xấu fail closed; full targeted tests.

**Commit:** `feat(contract): parse phases, profile, and per-task verify timeout`

**Ước lượng:** 1.5 ngày.

---

## E4 — Plan modes + chatbox-first review

**Mục tiêu:** user chọn phase manual hoặc nhận đề xuất AI/rules rồi tự chốt
**ngay trong chatbox**, không cần bấm phím TTY.

**Việc làm:**

1. `src/waker/cli.py`:
   - `waker plan --phases none|manual|auto`;
   - `waker plan --profile small|medium|large|overnight`;
   - `waker plan --json` trả phase/task/budget để agent đọc;
   - `--yes` chỉ dùng khi plan sạch và không còn câu hỏi blocking.
2. `auto`:
   - ưu tiên phase có sẵn trong prompt/task;
   - fallback rule-based theo scope/module;
   - `--via opencode` mới gọi AI; output phải qua validator.
3. **Chatbox-first (surface chính)**:
   - Agent gọi `waker plan --json`, rồi trả lời bằng hội thoại:
     ```text
     Mình đề xuất 3 phase (profile overnight, 8h cap):

     P1  Auth & JWT       T1–T3   45m
     P2  Stripe Payment   T4–T7   2h
     P3  E2E & Security   T8–T9   30m

     Gõ "ok" hoặc "1" để chạy; hoặc nói muốn sửa, ví dụ:
     "tăng P2 lên 3h, P1 còn 30m".
     ```
   - Task lớn: **không start** cho đến khi user trả lời rõ ràng
     `ok` / `1` / `chạy`.
   - User sửa bằng ngôn ngữ tự nhiên: agent map yêu cầu → sửa `tasks.yaml` →
     chạy lại lint → in diff ngắn → xác nhận → mới được start.
   - Không cần parser ngôn ngữ tự nhiên trong core; agent là lớp hội thoại,
     contract + lint là lớp kiểm chứng.
   - Không yêu cầu `[Enter]/e/p/m/q` trong chatbox.
4. **Small-task fast path** (ngoại lệ có kiểm soát):
   - Chỉ khi user đã gọi `/waker`, prompt rõ goal + scope + verify, tối đa
     2 task, 1 phase, không có câu hỏi blocking.
   - Agent có thể tự chạy ngầm ngay, không hỏi phase; vẫn phải tạo contract,
     lint sạch và ghi `approved_by: /waker-fast-path`.
   - Nếu thiếu scope/verify hoặc có >2 task → quay lại review/Grill-Me.
5. **TTY fallback**:
   - `waker plan` chạy trực tiếp trong terminal vẫn có thể dùng
     `[Enter] accept / e edit / p profile / m manual / q cancel`.
   - Non-TTY/chatbox: in plan/JSON rồi exit; tuyệt đối không chờ phím.
6. Cập nhật `SKILL.md` để hướng dẫn agent dùng flow chatbox này.
7. Tests CLI: none/manual/auto, `--json`, `--yes`, invalid AI output fallback,
   non-TTY không treo; test hội thoại thủ công cho sửa phase bằng lời.

**Files:**

- `src/waker/cli.py`
- `src/waker/planner.py` / `budget.py` nếu cần helper
- `tests/test_cli.py`
- `.opencode/skills/waker/SKILL.md`
- `docs/GRILL_ME.md` (nếu có)

**Gate:** user có thể chọn/sửa phase bằng chat; task lớn chưa duyệt thì chưa
chạy; task nhỏ rõ ràng có fast path; terminal không bị treo.

**Commit:** `feat(plan): add phase modes and chatbox review`

**Ước lượng:** 2 ngày.

---

## E5 — Timeout runtime + TIMEOUT diagnosis (v2.2)

**Mục tiêu:** profile thực sự có hiệu lực và timeout được báo đúng loại; chưa
hard-stop theo phase.

**Việc làm:**

1. `src/waker/engine.py` + `state.py`: áp dụng profile, lưu `profile`,
   timeout values và lý do timeout vào `run.json`.
2. `src/waker/detector.py` + `models.py`:
   - thêm diagnosis `TIMEOUT` cho `max_wall_clock` (không gộp `BREAKER`);
   - `turn_timeout` vẫn là event `turn_end.timed_out`, có kick/report rõ.
3. `src/waker/evidence.py`: verify timeout trả `timed_out` riêng, không tự coi
   là code fail.
4. `src/waker/cli.py`: `start --profile`, `status` hiển thị profile/timeout;
   `resume` giữ budget hiện tại.
5. Tests với fake agent/verify command có timeout ngắn; kiểm tra run.json/events.
6. Không phase hard-stop ở phase này.

**Files:**

- `src/waker/engine.py`
- `src/waker/state.py`
- `src/waker/models.py`
- `src/waker/detector.py`
- `src/waker/evidence.py`
- `src/waker/cli.py`
- `tests/test_engine.py`, `tests/test_state.py`, `tests/test_detector.py` nếu có

**Gate:** full pytest xanh; timeout reason đúng; backward compatibility với
`medium`; không kill phase giữa turn.

**Commit:** `feat(engine): apply timeout profiles and report TIMEOUT`

**Ước lượng:** 1.5 ngày.

---

## E6 — UI phase/budget integration

**Mục tiêu:** người dùng thấy phase và budget thật trên Cyber-Deck.

**Việc làm:**

1. `src/waker/ui.py`:
   - ViewModel đọc `phase`, `profile`, budget remaining từ run/contract;
   - thêm dòng `PHASE n/N ... elapsed / budget`;
   - màu xanh/vàng/đỏ theo 80%/95%;
   - event stream nhận `budget_warning`/`timeout` nếu có.
2. `waker status --budget` (nếu chưa làm ở E5).
3. Compact 80 cột: gộp phase + budget một dòng; không tràn footer.
4. `scripts/preview_waker_deck.py`: cập nhật trạng thái/budget demo nếu cần.
5. Tests: 120/80 line budget, phase row, no fake numbers, NO_COLOR.

**Files:**

- `src/waker/ui.py`
- `scripts/preview_waker_deck.py`
- `tests/test_ui.py`
- `src/waker/cli.py` (status)

**Gate:** không vượt 22 dòng @120 / 24 dòng @80; UI chỉ dùng dữ liệu thật.

**Commit:** `feat(ui): show phase and timeout budget on Cyber-Deck`

**Ước lượng:** 1 ngày.

---

## E7 — v2.2.0 release gate

**Mục tiêu:** đóng gói phần cơ bản, chưa hard phase enforcement.

**Việc làm:**

1. README: profile flags, phase schema, Grill-Me, timeout meanings.
2. CHANGELOG + skill docs.
3. Version chỉ đổi sau khi user duyệt; build package, twine check.
4. Chạy full pytest, demo prompt mơ hồ/rõ, demo timeout profile.
5. Demo chatbox: dự án lớn → phase plan → `ok`; sửa `P2=3h` bằng lời;
   task nhỏ rõ → fast path không hỏi.
6. Không tag/publish nếu chưa có lệnh.

**Files:** `README.md`, `CHANGELOG.md`, `pyproject.toml` (nếu duyệt version),
`docs/`, `.opencode/skills/waker/SKILL.md`.

**Gate:** full pytest 100%; package build OK; user duyệt release.

**Ước lượng:** 0.5 ngày.

---

## E8 — v2.3.0 phase-budget enforcement (deferred)

Chỉ bắt đầu sau khi v2.2.0 được duyệt.

**Việc làm:**

1. `state.py`: phase elapsed, phase status, timeout reason.
2. `engine.py`: phase_started/budget_warning/phase_completed/phase_timeout.
3. Soft warning 80%, hard stop 100% ở turn boundary.
4. `resume --extend` + event `budget_extended`; không reset evidence.
5. UI budget bar/remaining; lịch sử run để gợi ý budget.
6. `waker grill` + `questions.yaml` fail-closed nếu instruction-only không đủ.
7. Tests: phase budget, extend, report, phase timeout priority.

**Ước lượng:** 3–4 ngày.

---

## Test matrix

| Lớp | Kiểm tra |
|---|---|
| Unit | duration/profile, phase validation, contract round-trip |
| Planner | YAML cũ/mới, invalid phase, `--phases` modes, `--yes` |
| Chatbox UX | phase plan, `ok`, sửa budget bằng lời, fast path nhỏ, non-TTY |
| Engine | profile values, turn timeout, wall-clock TIMEOUT, verify timeout |
| State | run.json fields, resume preservation |
| UI | phase row, color thresholds, 120/80 columns |
| Safety | no auto-answer, no auto-start, no mid-run phase change, tamper |
| Regression | full pytest, existing small/medium runs unchanged |

## Rủi ro & cách chặn

- **Backward compatibility:** task cũ không có phase → `P1`; test load YAML cũ.
- **Contract hash:** mọi field mới phải đi vào hash/freeze; sửa sau start → `TAMPER`.
- **AI đề xuất sai:** validator + fallback rules/manual; không auto-start.
- **Timeout test treo:** dùng fake agent/verify ngủ ngắn; không dùng sleep dài.
- **UI tràn:** test 80/120 cột; compact budget một dòng.
- **Release sớm:** E8 tách khỏi E7; không tag/publish nếu chưa duyệt.

## Approval checklist

- [ ] Đồng ý thứ tự E0 → E7 cho v2.2.0.
- [ ] Đồng ý E8 (phase hard enforcement) để v2.3.0.
- [ ] Đồng ý Grill-Me chỉ nằm trong `SKILL.md` ở bản này.
- [ ] Đồng ý user phải duyệt phase plan trước khi freeze.
- [ ] Đồng ý không đổi `medium` defaults hiện tại.
