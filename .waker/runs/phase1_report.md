# Phase 1 — Báo cáo nghiệm thu (Autonomous Overnight Run)

**Dự án:** waker-ai
**Repo:** `C:\Users\tuank\waker-ai` (git repo riêng, nhánh `main`)
**Thời điểm:** 2026-11-07, chạy tự hành ban đêm
**Trạng thái:** ✅ HOÀN TẤT — `pytest tests/` exit code **0**
**Cam kết:** Đã DỪNG sau Phase 1, không tự ý sang Phase 2.

---

## 1. Kết quả kiểm thử (bằng chứng thép)

```bash
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe -m pytest tests/
```

```
60 passed in 91.50s (0:01:31)
EXIT=0
```

| Thông số | Giá trị |
|---|---|
| Số test | **60** |
| Passed | 60 |
| Failed | 0 |
| Thời gian | ~91 giây |
| Exit code | **0** |
| Python | 3.12.10 |
| pytest | 9.2.0 |
| rich | 15.0.0 |
| PyYAML | 6.0.3 |
| OS | Windows (win32) |

---

## 2. Phạm vi đã giao (đối chiếu yêu cầu Phase 1)

| Yêu cầu | Trạng thái | Nơi thực hiện |
|---|---|---|
| Khởi tạo repo chuẩn (`pyproject.toml`, `src/waker/`, `tests/`) | ✅ | `pyproject.toml`, `src/waker/`, `tests/` |
| `waker plan --planner rules` — parser 4 rổ, 0 token | ✅ | `src/waker/planner.py` |
| `state.py` — run state, session id, checkpoint baseline | ✅ | `src/waker/state.py` |
| `evidence.py` — scope diff + hash test (tamper) | ✅ | `src/waker/evidence.py` |
| `detector.py` — pure `Observation -> Diagnosis` | ✅ | `src/waker/detector.py` |
| Ledger tích luỹ + audit trail `kick-N.json` | ✅ | `state.py`, `engine.py` |
| `tests/fake_lazy.py` — 4 ca bệnh + vòng kick | ✅ | `tests/fake_agent.py` (6 modes) |
| `waker status` (Markdown) | ✅ | `src/waker/ui.py` |
| `waker watch` (Rich Live) | ✅ | `src/waker/ui.py` |

**Quy mô code:** 2.630 dòng `src/` + 821 dòng `tests/` = **3.451 dòng**.

---

## 3. Bằng chứng vòng lặp kick chạy thật (không chỉ unit test)

Chạy E2E bằng chính CLI `waker.exe` trên một repo tạm, agent giả mode `lazy`
(làm T1 rồi tự dừng, báo "Em mới làm xong Task 1 thôi"):

```
=== RUN exit 0
**waker · run 993e46d5 · 2/2 — 100%**
`████████████████`  ⏱ 00:02  🔁 1/3  🧪 ✅ PASS

|   | Task | Việc | Bằng chứng | Cổng |
|---|------|------|-----------|------|
| ✅ | T1 | write src/a.txt | src/a.txt | pass |
| ✅ | T2 | write src/b.txt | src/b.txt | pass |

Chẩn đoán cuối: **DONE** · trạng thái: `DONE`
kết luận: DONE (exit 0)
```

Lịch sử kick trong `report.md` của run đó:

```
- kick 0: PARTIAL     ← agent làm 1/2 rồi dừng
- kick 1: DONE        ← waker đánh thức, agent làm nốt
```

→ Chứng minh đúng luồng: **không exit khi agent tự dừng; chỉ exit khi 2/2 task có
evidence + test xanh.**

---

## 4. Bốn ca bệnh — mỗi ca có test riêng

| Ca bệnh | Agent giả | Kỳ vọng | Test |
|---|---|---|---|
| Làm nửa rồi dừng (Premature Exit) | `lazy` | `PARTIAL` → kick → `DONE` | `test_lazy_agent_is_kicked_until_done` |
| Nói láo (Hallucinated Completion) | `liar` | `FALSE_DONE` lặp → `BREAKER` (exit 2), **không bao giờ** xanh | `test_liar_agent_never_gets_a_false_green` |
| Tráo test (Tamper) | `tamper` | `TAMPER` → revert test → `BREAKER` | `test_tamper_agent_is_reverted_and_never_wins` |
| Đơ máy (Freeze) | `freeze` | `FROZEN` sau timeout → `BREAKER` | `test_frozen_agent_is_detected` |
| Bị chặn thật (Blocked) | `blocked` | `BLOCKED` (exit 3), **không đốt kick** | `test_blocked_agent_stops_without_burning_kicks` |
| Làm đúng (Happy path) | `good` | `DONE` trong 1 turn, đủ report/prompt/result | `test_good_agent_finishes_in_one_turn` |

Test `tamper` còn kiểm thêm: **file test được khôi phục về baseline ngay cả ở
turn cuối** (không để lại exam đã bị sửa).

---

## 5. Kiến trúc đã hiện thực

```
prompt ──► planner (rules, 0 token) ──► tasks.yaml
                                           │
                                           ▼
                    ┌──────────── engine.py ────────────┐
                    │ spawn agent (adapter)             │
                    │   ↓                               │
                    │ observe: git diff + untracked     │
                    │ verify:  scope ∩ diff + command   │
                    │ hash:    tests/** (tamper)        │
                    │   ↓                               │
                    │ detector.diagnose(Observation)    │
                    │   ↓                               │
                    │ checkpoint + build wake prompt     │
                    └───────────────┬───────────────────┘
                                    ▼
                         ledger.json + events.jsonl
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
              waker status (md)              waker watch (Rich)
```

**Bất biến đã giữ:**

1. Không có nhánh nào trong engine exit vì agent nói "xong".
2. `done(T)` = `(diff ∩ scope ≠ ∅) AND (verify exit 0)`.
3. Test hash đổi → `TAMPER` xếp **trên** `DONE`.
4. Mỗi turn ghi `prompt.txt` + `result.json` (audit được nguyên văn đã gửi).
5. Mọi state ghi atomic, ledger append-only, UI chỉ render từ ledger.

---

## 6. Sai lệch so với plan.md (đã ghi rõ lý do)

| # | Sai lệch | Lý do |
|---|---|---|
| 1 | `detector` đánh giá `BREAKER` **trước** `PARTIAL` | Nếu để sau, run đã chạm `max_kicks` sẽ trả `PARTIAL` mãi và không bao giờ dừng. Đã ghi comment trong code. |
| 2 | Thêm 2 nhãn `BLOCKED`, `SUSPECT_TEST` ngoài 5 nhãn yêu cầu | `BLOCKED` là lối thoát hợp pháp; `SUSPECT_TEST` bảo vệ worker khi test bị viết sai. Cả hai đã có trong plan.md §7. |
| 3 | Adapter mới có `generic` (T2) + `opencode` (T1 skeleton) | Phase 1 chỉ yêu cầu core; Claude/PTY T3 là Phase 2. |
| 4 | Chưa có daemon `waker serve` / `install-skill` | Không nằm trong danh sách Phase 1 được giao. |
| 5 | `--planner` chỉ nhận `rules` | Đúng yêu cầu Phase 1 (0 token). `llm` là Phase 2. |
| 6 | Vai "Test Author" chưa code | Là thiết kế Phase 2 (§25 plan.md), không thuộc Phase 1. |
| 7 | `waker watch` không có unit test | Bản chất là vòng lặp Live vô hạn; đã verify `build_rich` qua import và render markdown. Ghi nhận là nợ kỹ thuật. |

---

## 7. Bug thật gặp trong đêm và cách sửa

| Bug | Triệu chứng | Sửa |
|---|---|---|
| Emoji viết dạng surrogate pair (`"\ud83d\udd34"`) | `UnicodeEncodeError: surrogates not allowed` khi ghi report | Thay bằng code point thật (`\U0001F534`) |
| `_split_units` cắt cả dấu phẩy trong metadata | `scope: docs/**, verify: ...` bị tách thành 3 task rỗng | Không split dòng có metadata |
| Console Windows cp1252 | CLI crash khi in bảng có emoji ra pipe | `sys.stdout.reconfigure(utf-8)` + `PYTHONIOENCODING=utf-8` cho agent con |
| Revert test chạy **sau** kiểm tra terminal | Turn cuối bị TAMPER thì test không được khôi phục | Chuyển revert lên trước `_budget_guard` |
| `prev_diff_hash` lưu nhầm fingerprint | `FROZEN` không bao giờ trigger | Thêm `last_diff_hash` riêng vào `RunState` |
| Lint báo sai với file mới | `scope: src/a.txt` (chưa tồn tại) bị warning | Chỉ warning cho scope dạng thư mục/wildcard |
| UTF-8 BOM từ PowerShell | `Set-Content -Encoding utf8` thêm `\uFEFF` làm hỏng dòng `Phase 1:` | Đọc file bằng `utf-8-sig` |

---

## 8. Giới hạn đã biết (Phase 2)

1. **Chưa kill process tree trên Windows** — timeout mới kill shell con, chưa kill cháu. Cần `taskkill /T /F` hoặc Job Object.
2. **`FROZEN` chỉ dựa trên timeout của adapter**, chưa có live probe (stdout/event age).
3. **Verify chạy mọi task mỗi boundary** — đúng nhưng chưa tối ưu cho repo lớn (scheduling theo scope là Phase 2).
4. **OpenCode adapter chưa test live** — cần parse `--format json` và xử lý `ConnectionRefused` khi model chết (đã gặp thật).
5. **Chưa có cost tracking** từ event JSON.
6. **`waker watch`** chưa có test tự động.

---

## 9. Cách tái lập trong 2 lệnh

```powershell
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe -m pytest tests/
```

Demo vòng kick (repo tạm, agent giả lười):

```powershell
C:\Users\tuank\waker-ai\.venv\Scripts\python.exe `
  C:\Users\tuank\AppData\Local\Temp\opencode\waker_demo.py
```

Kết quả mong đợi: `RUN exit 0`, `2/2 — 100%`, lịch sử `kick 0: PARTIAL` → `kick 1: DONE`.

---

## 10. Checklist nghiệm thu

- [x] Repo chuẩn, cài được (`pip install -e .`, `waker --version` → `0.1.0a1`)
- [x] Parser 4 rổ deterministic, 0 token
- [x] Lint hợp đồng: thiếu scope/verify, id trùng, scope overlap, verify rỗng → chặn
- [x] State/ledger/events/checkpoint trên đĩa
- [x] Tamper detection + revert
- [x] Detector thuần, test đủ 11 nhánh
- [x] Engine loop chứng minh bằng 6 agent giả
- [x] `waker status` markdown + `waker watch` Rich
- [x] 60 test, **exit code 0**
- [x] Report này
- [x] **Dừng lại, chờ nghiệm thu — không sang Phase 2**

---

## 11. Đề xuất cho Phase 2 (chờ duyệt)

1. Daemon `waker serve` + `start --detach` + skill cho OpenCode/Claude/Gemini.
2. Adapter OpenCode T1 đầy đủ: parse JSON event, session resume thật, `doctor`.
3. Kill process tree + live freeze probe.
4. Test Author (§25) + `waker plan lint` cho `plan.md`.
5. Cost guard từ token usage.

**Không có thay đổi nào được thực hiện cho các mục trên trong đêm nay.**
