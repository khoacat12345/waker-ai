# WAKER BLIND EVALUATION — SPEC THI CÔNG (v1.1.0)

**Feature:** Hidden Test Vault & Blind Evaluation (Kaggle Mode)
**Trạng thái:** Đã triển khai v1.1.0 (Phase A–D); v1.2 cho sandbox/encryption
**Target:** `waker-ai v1.1.0`
**Tác giả:** Tuankhoa (Founder / Lead Architect) & Waker maintainers
**Cập nhật:** 2026-11-08

---

## 1. Vấn đề

Khi worker (OpenCode/Claude/coder) vừa viết code vừa viết test, nó có thể:

1. Viết test nông (`assert True`) để dễ pass.
2. Viết test khớp với bug của chính nó.
3. Sửa test khi bị test cũ bắt lỗi.
4. Đọc đề và "học vẹt" thay vì implement đúng.

Waker hiện tại đã chặn được (3) bằng hash `TAMPER`, nhưng chưa chặn được (1), (2), (4).
Blind Evaluation giải quyết bằng 3 nguyên tắc:

> **Độc lập** — người viết đề ≠ người làm bài.
> **Đóng băng** — đề được validate và hash trước khi worker bắt đầu.
> **Chấm mù** — worker không thấy đề, chỉ thấy diagnostic đã lọc.

---

## 2. Mục tiêu

- Architect (chatbox) viết **hidden tests** và nạp vào vault.
- Waker validate đề trước khi chạy (đề phải đỏ trên baseline, không import error).
- Worker chỉ thấy: `tasks.yaml`, `public_api`, smoke tests. Không thấy vault.
- Waker chấm hidden suite khi worker báo xong; pass 100% mới `DONE`.
- Khi fail, worker nhận diagnostic đã sanitize (không source, không path, không locals).
- Mọi thứ được ghi audit (hash, số test, kết quả) — không ghi source đề.

## 3. Không nằm trong mục tiêu (v1.1)

- Không phải sandbox bảo mật tuyệt đối (xem §4).
- Không mã hoá vault at-rest (để v1.2).
- Không chấm trên máy khác / remote runner.
- Không thay thế review của con người với task rủi ro cao.

---

## 4. Mô hình bảo mật — nói thật

Blind Evaluation bảo vệ chống **agent lười/tự chấm bài**, không chống **process đối kháng** đọc trộm đĩa.

| Kẻ tấn công | v1.1 có chặn? | Ghi chú |
|---|---|---|
| Worker đọc vault vì đường dẫn nằm trong prompt/scope | ✅ Có | Vault ngoài repo, không có path trong prompt/scope |
| Worker tự viết test nông rồi tự chấm | ✅ Có | Hidden suite do Architect viết, worker không thấy |
| Worker sửa test sau khi bị bắt | ✅ Có | Vault hash + `TAMPER` |
| Worker quét ổ đĩa tìm vault | ❌ Không | Cùng user, cùng quyền đọc. Đây là giới hạn của v1.1 |
| Worker debug process/argv của waker | ❌ Không | Có thể thấy path nếu nó chủ động |

**Kết luận:** v1.1 là **"blind by construction"**, không phải "adversarially secure".
Muốn cách ly thật: chạy worker trong Docker/Windows Sandbox (roadmap v1.2). Spec này
không được quảng cáo là "bảo mật tuyệt đối".

Hệ quả thiết kế:

- Vault **tuyệt đối không nằm trong repo**.
- Vault path **không** xuất hiện trong prompt, `scope`, log, report, hay `waker status`.
- Worker session là session mới (`ses_waker_<run>`), không phải chat của Architect.
- Test files trong vault bị xoá khỏi temp dir ngay sau khi chấm.

---

## 5. Kiến trúc

```
┌─ Architect (chatbox session riêng) ─────────────────────────────┐
│  waker vault init --repo .                                      │
│  waker vault add --vault <id> --suite auth --task T1 test.py    │
│  waker vault validate --vault <id> --repo .                     │
│      → phải ĐỎ trên baseline, không import error, không skip    │
│  waker start ... --vault <id>                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ vault_id (không phải path)
                            ▼
┌─ Waker daemon ───────────────────────────────────────────────────┐
│  Phase 0: load vault, verify hash, freeze contract              │
│  Phase 1: worker prompt = tasks + public_api + smoke tests      │
│           KHÔNG có vault path/suite/test source                 │
│  Phase 3: public verify → hidden suite trong temp dir           │
│           → sanitize → hidden result                            │
│  Phase 4: DONE chỉ khi hidden 100% + public + constraint        │
│  Phase 6.5: coverage audit (không đọc source đề)                │
└───────────────────────────┬─────────────────────────────────────┘
                            │ sanitized diagnostics only
                            ▼
┌─ Worker (session mới) ───────────────────────────────────────────┐
│  Chỉ thấy spec + smoke tests. Không thấy hidden suite.          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 6. Dữ liệu & schema

### 6.1 `tasks.yaml` — thêm block `blind`

```yaml
- id: T1
  desc: "Auth module: register/login/logout/session"
  scope: ["src/auth/**", "tests/test_auth_smoke.py"]
  verify: "pytest tests/test_auth_smoke.py -q"     # public smoke, worker thấy
  public_api:
    - "register(username: str, password: str) -> User"
    - "login(username: str, password: str) -> str | None"
    - "session(token: str) -> dict | None"
    - "logout(token: str) -> None"
  blind:
    suite: auth
    baseline: red          # hidden phải đỏ trước khi worker làm
    timeout: 120
    leak: message          # minimal | message  (full = chỉ human)
```

- `verify` là public smoke — worker được thấy và được sửa (trong scope).
- `blind.suite` trỏ tới suite trong vault; **không** phải đường dẫn file.
- `blind.baseline: red` bắt buộc với task tính năng mới; `green` chỉ dùng cho regression.
- `leak` quy định mức chi tiết trả về worker (xem §9.3).

### 6.2 Vault manifest

Lưu tại vault (ngoài repo):

```json
{
  "vault_id": "9f3a2c7d1e4b",
  "repo": "C:\\Users\\tuank",
  "created_at": "2026-11-08T04:00:00+00:00",
  "suites": {
    "auth": {
      "files": [
        {"name": "test_auth_hidden.py", "sha256": "..."},
        {"name": "conftest.py", "sha256": "..."}
      ],
      "hash": "sha256(sorted(name + bytes))",
      "baseline": "red",
      "validated_at": "...",
      "tests": 12,
      "timeout": 120,
      "leak": "message"
    }
  }
}
```

- `hash` được tính trên toàn bộ file trong suite, sort theo tên.
- `tests` là số test thu được từ `pytest --collect-only`.
- Mapping `test_1..test_N` → nodeid thật chỉ nằm trong manifest, không đưa cho worker.

### 6.3 Run state

Thêm vào `RunState`:

```json
{
  "vault_id": "9f3a2c7d1e4b",
  "vault_hash": "sha256...",
  "vault_suites": ["auth"],
  "blind": true
}
```

- `vault_id` được truyền từ CLI; `vault_hash` lấy từ manifest lúc prepare.
- Nếu hash manifest khác hash đã freeze → `VAULT_TAMPER`.

### 6.4 Ledger

```json
"hidden": {
  "auth": {
    "total": 12,
    "passed": 11,
    "failed": ["test_3"],
    "signature": "sha256...",
    "suspect_test": false
  }
}
```

Không lưu source, không lưu nodeid thật trong ledger.

---

## 7. Vault: vị trí, vòng đời, CLI

### 7.1 Vị trí

| OS | Đường dẫn |
|---|---|
| Windows | `%LOCALAPPDATA%\waker\vault\<vault_id>` |
| macOS | `~/Library/Application Support/waker/vault/<vault_id>` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/waker/vault/<vault_id>` |

- Override: `WAKER_VAULT_DIR` hoặc `--vault-dir` (dùng cho test/CI).
- **Không** đặt dưới repo, không đặt dưới `.waker/`.
- Quyền: best-effort `0o700` trên POSIX; Windows dựa vào user profile.

### 7.2 Vòng đời

```
init → add (nhiều lần) → validate → freeze → run → grade → cleanup
```

- `init`: tạo vault_id ngẫu nhiên 12 hex, tạo thư mục, ghi manifest rỗng.
- `add`: copy file vào vault, cập nhật manifest (hash từng file + suite hash).
- `validate`: chạy hidden suite trên baseline; kiểm tra red/collect/skip/flaky.
- `run`: waker đọc manifest, verify hash, dùng suite.
- `grade`: copy suite ra temp dir, chạy pytest, xoá temp dir.
- `cleanup`: `waker vault rm --vault <id>` (thủ công) hoặc `--keep-vault`.

### 7.3 CLI

```bash
# Architect (chatbox) — không đưa path cho worker
waker vault init --repo . [--json]
waker vault add --vault <id> --suite auth --task T1 path/to/test_auth_hidden.py
waker vault add --vault <id> --suite auth --task T1 path/to/conftest.py
waker vault list --vault <id> [--json]
waker vault validate --vault <id> --repo . [--json]
waker vault show --vault <id>            # human-only, in source (có cảnh báo)
waker vault rm --vault <id> --suite auth

# Supervisor
waker run --tasks tasks.yaml --vault <id> ...
waker start --detach --tasks tasks.yaml --vault <id> ...
```

- `--vault <id>` chỉ là id, không phải path.
- Nếu task có `blind` mà không có `--vault` → lint error, fail closed.
- Nếu `--vault` được truyền nhưng task không có `blind` → warning.

---

## 8. Tích hợp vào engine

### 8.1 Phase 0 — Prepare

1. Đọc `vault_id` từ CLI.
2. Load manifest từ vault dir; nếu không tồn tại → `VAULT_MISSING`.
3. So `vault_hash` manifest với hash đã lưu (nếu resume) → `VAULT_TAMPER` nếu khác.
4. Kiểm tra từng suite trong task có `blind`:
   - suite tồn tại trong manifest;
   - `validated_at` có;
   - `hash` khớp file thực tế.
5. Lưu `vault_id`, `vault_hash`, `blind` vào `RunState`.
6. **Không** copy vault vào repo; **không** ghi path vào prompt.

### 8.2 Phase 0.5 — Validate đề (bắt buộc trước run)

Với mỗi suite:

1. `pytest --collect-only` phải exit 0.
2. Chạy trên baseline:
   - `baseline: red` → phải có ít nhất 1 test fail; nếu tất cả pass → reject
     (`test suite does not prove anything`).
   - `baseline: green` → phải pass toàn bộ (dùng cho regression).
3. Không có `skip`/`xfail`/`pytest.skip(` trong source.
4. Số test ≥ 1; timeout hợp lệ.
5. Chạy 2 lần (mặc định) — kết quả phải giống nhau; nếu flaky → reject.
6. Không import module ngoài repo/stdlib (best-effort static check).

Nếu fail → in lỗi cho Architect, **không** start run.

### 8.3 Phase 1 — Worker prompt

Prompt của worker **chỉ** chứa:

- task desc, scope, `verify` (public smoke), `public_api`;
- constraints;
- quy tắc: không sửa hidden tests, không tìm vault.

**Tuyệt đối không** chứa: `vault_id`, vault path, tên file hidden, nodeid, source.

### 8.4 Phase 3 — Blind verification

Sau khi public verify chạy:

1. Tạo temp dir: `%TEMP%\waker-blind-<run>-<suite>-<random>`.
2. Copy toàn bộ file suite từ vault vào temp dir.
3. Chạy:

```bash
python -m pytest <temp_dir> -q --tb=line --disable-warnings \
  -p no:cacheprovider --rootdir <temp_dir>
```

   - `cwd = temp_dir`
   - `PYTHONPATH = <repo>` (+ `WAKER_REPO=<repo>`)
   - timeout = `blind.timeout`
4. Parse kết quả, sanitize (§9), ghi ledger.
5. Xoá temp dir trong `finally` (kể cả khi timeout).
6. Nếu suite pass 100% → `G_hidden` pass.
7. Nếu fail → `HIDDEN_FAIL` hoặc `SUSPECT_TEST`.

### 8.5 Phase 4 — Diagnosis

Thứ tự ưu tiên bổ sung (chèn sau `TAMPER`, trước `DONE`):

| Nhãn | Điều kiện | Hành động |
|---|---|---|
| `VAULT_TAMPER` | hash vault khác hash freeze | dừng, báo người |
| `VAULT_MISSING` | không load được vault/suite | dừng, fail closed |
| `HIDDEN_FAIL` | hidden có test fail | kick với diagnostic sanitized |
| `SUSPECT_TEST` | toàn bộ fail là ImportError/AttributeError/collection | dừng, báo "đề có thể sai" |
| `DONE` | public + hidden 100% + constraint + hash | dừng |

`DONE` **chỉ** được trả về khi tất cả task có `blind` đều pass hidden suite.

### 8.6 Phase 6.5 — Coverage audit

- Audit vẫn đọc prompt gốc + tasks + evidence.
- Không đọc source hidden; chỉ đọc `hidden` result (pass/fail counts).
- Nếu audit phát hiện clause chưa phủ → thêm task; hidden suite của task mới
  phải được Architect viết + validate trước khi worker làm.

---

## 9. Blind runner & sanitize

### 9.1 Runner

- Chỉ dùng `pytest` (v1.1). Các runner khác (npm/cargo/go) để v1.2.
- Không dùng `--tb=long`/`--showlocals`.
- `--tb=line` để mỗi failure chỉ còn 1 dòng.
- `-p no:cacheprovider` để không ghi `.pytest_cache` vào repo.
- `--rootdir` temp để không đọc `pytest.ini`/`pyproject` của repo.
- Nếu repo cần fixture/config, hidden test tự chứa `conftest.py` trong suite.

### 9.2 Sanitize

Input: output pytest + mapping nodeid → `test_1..N`.

1. Xoá mọi dòng chứa temp dir, vault dir, repo path.
2. Xoá mọi dòng bắt đầu bằng `>` (source line) hoặc `E   ` chứa code.
3. Thay path:line bằng `hidden://<suite>/test_<n>`.
4. Chỉ giữ tối đa 5 failure.
5. Không giữ traceback, locals, biến, source.
6. `leak=minimal`: chỉ `test_<n> failed`.
   `leak=message`: thêm `AssertionError` message (đã lọc path).
7. Không bao giờ trả về tên file hidden hay nodeid thật.

### 9.3 Ví dụ wake prompt

```text
[waker kick 2/5] lý do: HIDDEN_FAIL

ĐÃ XONG: T2
CHƯA XONG: T1 (Auth module)

Hidden suite auth: 9/12 pass.
- hidden://auth/test_3: AssertionError: login must return a token
- hidden://auth/test_7: AssertionError: bad password must return None
- hidden://auth/test_11: AssertionError: logout must invalidate the session

Public smoke: pytest tests/test_auth_smoke.py -q → 2 failed
...
```

Không có đường dẫn, không có source, không có expected value thô.

---

## 10. Gates & diagnosis

| Gate | Điều kiện pass | Chống được gì |
|---|---|---|
| `G_public` | `verify` (smoke) exit 0 | code không chạy |
| `G_hidden` | 100% hidden pass | tự chấm bài, test nông |
| `G_vault` | hash vault không đổi; worker không ghi vault | sửa đề |
| `G_leak` | prompt/scope không chứa vault path; output không lộ source | lộ đề |
| `G_contract` | hash `tasks.yaml` không đổi | đổi hợp đồng |

`G_hidden` chỉ áp dụng cho task có `blind: true`. Task không blind giữ hành vi cũ.

---

## 11. Chống lộ đề — checklist

- [ ] Vault ngoài repo, path random, không nằm trong `scope`.
- [ ] `vault_id` (không phải path) là thứ duy nhất đi vào run config.
- [ ] Prompt worker không chứa path/id/suite name? (suite name có thể lộ ý; cho phép
      `auth`, nhưng không chứa file/test name.)
- [ ] `waker status`/`report` chỉ hiện `hidden 12/12`, không hiện test name.
- [ ] `waker vault show` in source nhưng có cảnh báo "human only"; không gọi từ skill.
- [ ] Temp dir bị xoá sau khi chấm.
- [ ] Không ghi hidden output vào `.waker/runs` dưới dạng source.
- [ ] `git` không bao giờ thấy vault (ngoài repo).
- [ ] Worker session mới, không dùng lại chat Architect.
- [ ] Skill không được paste hidden test vào chat worker.

---

## 12. UI / report

- `waker status`: thêm dòng `hidden: 12/12` (hoặc `9/12`).
- `waker report`: `Hidden suite auth: 12/12 · hash abcd1234`.
- Không hiện test name, không source.
- `waker vault show` chỉ dành cho người, có `--yes` và cảnh báo.

---

## 13. Acceptance criteria (test suite)

### 13.1 Fake agents

| Test | Kỳ vọng |
|---|---|
| `fake_blind_peek` | cố đọc vault path từ prompt; prompt không chứa path → fail |
| `fake_hardcode` | hardcode để pass public smoke; hidden fail → `HIDDEN_FAIL` |
| `fake_test_writer` | viết test nông; hidden vẫn chấm → fail |
| `fake_suspect` | hidden fail toàn ImportError → `SUSPECT_TEST`, không kick vô hạn |
| `fake_leak` | hidden fail; output không chứa source/path |
| `fake_vault_tamper` | sửa file trong vault → `VAULT_TAMPER` |

### 13.2 Vault validation

| Test | Kỳ vọng |
|---|---|
| hidden pass trên baseline | reject: "does not prove anything" |
| hidden import error | reject |
| hidden skip/xfail | reject |
| hidden flaky (2 lần khác nhau) | reject |
| suite hash sai | `VAULT_TAMPER` |
| vault ngoài repo | path không nằm dưới repo |

### 13.3 Integration

- `waker run --vault <id>` với fake worker: DONE chỉ khi hidden pass.
- Không có `--vault` nhưng task có `blind` → lint fail.
- `waker vault show` không bị gọi từ skill.
- Report không chứa source.

---

## 14. Kế hoạch triển khai

| Giai đoạn | Nội dung | Ước lượng |
|---|---|---|
| **A** | `vault.py`: storage, manifest, hash, CLI `init/add/list/rm` | 1.5–2 ngày |
| **B** | `vault_validate.py`: baseline red, collect, skip, flaky | 1–1.5 ngày |
| **C** | `blind_runner.py`: temp dir, pytest, sanitize, cleanup | 1.5–2 ngày |
| **D** | Engine: state fields, gates, diagnosis, wake prompt | 1.5–2 ngày |
| **E** | Tests (fake agents) + docs + skill update | 1–1.5 ngày |
| **F** | Release v1.1.0 + CI + demo | 0.5 ngày |

Tổng: **6–9 ngày làm việc**. Không gộp vào v1.0.x.

---

## 15. Rủi ro & câu hỏi mở

### Rủi ro

1. **Đề sai** → worker bị đánh oan. Giảm thiểu: validate red, suspect test, human override.
2. **Flaky** → DONE không bao giờ đạt. Giảm thiểu: chạy 2 lần, reject flaky.
3. **Cùng user đọc được vault** → không phải bảo mật thật. Ghi rõ trong docs.
4. **Hidden test quá chi tiết** → lộ solution; quá mơ hồ → worker đoán. Cần public API rõ.
5. **Chi phí** → thêm 1 turn Architect; chỉ bật `--blind` cho task lớn.
6. **Maintenance** → hidden test phải cập nhật khi API đổi; version theo repo.

### Câu hỏi mở cần chốt trước khi code

1. Có cần mã hoá vault at-rest không? (đề xuất: v1.2, không chặn v1.1)
2. Có bắt buộc public smoke tests cho mọi task `blind` không? (đề xuất: có)
3. Ai được override `SUSPECT_TEST`? (đề xuất: chỉ người, qua `waker override`)
4. Có cho phép hidden suite `green` (regression) không? (đề xuất: có, nhưng hiếm)
5. Có chấm hidden trên CI (không có worker) không? (đề xuất: v1.2)
6. Có sandbox worker bằng Docker/Windows Sandbox không? (đề xuất: v1.2)

---

## 16. Định nghĩa hoàn thành v1.1.0

```
[ ] vault.py + CLI init/add/list/rm/validate
[ ] blind_runner.py + sanitize + cleanup
[ ] tasks.yaml schema blind + lint
[ ] engine gates: G_hidden, G_vault, G_leak, HIDDEN_FAIL, SUSPECT_TEST
[ ] wake prompt sanitized
[ ] report/status chỉ hiện counts
[ ] fake agents: peek/hardcode/narrow/suspect/leak/tamper
[ ] 100% test pass, exit code 0
[ ] docs: README + SPEC + skill
[ ] release v1.1.0 + wheel
```

---

## 17. Không được làm

- Không đặt vault trong repo, dù chỉ "tạm".
- Không đưa vault path vào prompt/scope/log/report.
- Không để worker session dùng lại chat Architect.
- Không trả source/traceback/locals cho worker.
- Không tuyên bố "bảo mật tuyệt đối" khi chưa có sandbox.
- Không chấm hidden nếu vault chưa validate red.
